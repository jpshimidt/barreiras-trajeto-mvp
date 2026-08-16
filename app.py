"""
Interface do app de elegibilidade a transporte escolar — São Paulo capital.

Protótipo de validação da regra. Endereços informados ficam na sessão Streamlit
no servidor até logout ou fim da sessão — não há banco de dados nem analytics.

    streamlit run app.py
"""

from __future__ import annotations

import os
from pathlib import Path

import folium
import streamlit as st
from streamlit_folium import st_folium

from core.barreiras import (
    BUFFER_M_PADRAO,
    Barreira,
    barreiras_atingidas,
    proximas_da_rota,
)
from core.barreiras_cache import barreiras_carregadas, descricao_cadastro
from core.decisao import decidir
from core.erros import ErroExterno
from core.geo_limites import exigir_coordenada_em_sao_paulo
from core.auth_app import exigir_login, usuario_e_admin
from core.rate_limit import consumir_calculo, consumir_geocodificacao
from core.endereco_maps import (
    EXEMPLO_ENDERECO_MAPS,
    Local,
    geocodificar,
    parse_endereco_maps,
    resolver_geocodificacao,
)
from core.google_geo import (
    buscar_sugestoes_endereco,
    detalhes_place_id,
    extrair_coordenadas_maps_url,
    ler_google_api_key,
)
from core.routing import Rota, rota_a_pe
from core.ui import aplicar_estilo, chips_mapa, lead, marca, passos_consulta, sidebar_marca, veredito

ARQUIVO_BARREIRAS = Path(__file__).parent / "dados" / "barreiras.geojson"

COR_ROTA = "#1f6feb"
COR_BARREIRA = "#d1242f"

st.set_page_config(page_title="Transporte escolar — elegibilidade", page_icon="🚌", layout="wide")


# --------------------------------------------------------------------------- #
# Recursos
# --------------------------------------------------------------------------- #


def barreiras_do_cadastro() -> list[Barreira]:
    """Cadastro público de barreiras (cache compartilhado com a página admin)."""
    return barreiras_carregadas(ARQUIVO_BARREIRAS)


def _ler_api_key_ors() -> str | None:
    """Chave ORS quando configurada; None se ausente (geocodificação segue via Nominatim)."""
    try:
        if "ORS_API_KEY" in st.secrets:
            chave = str(st.secrets["ORS_API_KEY"]).strip()
            if chave:
                return chave
    except Exception:
        pass
    chave = os.environ.get("ORS_API_KEY", "").strip()
    return chave or None


def obter_api_key() -> str:
    """
    No Streamlit Cloud a chave vem de Settings → Secrets; local, da variável de
    ambiente. `st.secrets` estoura quando não há arquivo nenhum, daí o try.
    """
    chave = _ler_api_key_ors()
    if not chave:
        raise ErroExterno(
            "Chave do OpenRouteService não configurada. "
            "No Streamlit Cloud: Settings → Secrets, com `ORS_API_KEY = \"...\"`."
        )
    return chave


# NOTA DELIBERADA: geocodificação e roteamento NÃO são cacheados.
# `st.cache_data` guardaria endereços residenciais de crianças na memória do
# servidor, compartilhados entre sessões — o oposto do que este protótipo promete.
# São ~10 consultas por dia; não há problema de desempenho a resolver.


# --------------------------------------------------------------------------- #
# Mapa
# --------------------------------------------------------------------------- #


def montar_mapa(rota: Rota, casa: Local, escola: Local, atingidas: list[Barreira]) -> folium.Map:
    mapa = folium.Map(tiles="cartodbpositron", control_scale=True)

    nomes_atingidos = {b.id for b in atingidas}
    # Só o que está perto da rota: o cadastro real tem megabytes e travaria o navegador.
    for barreira in proximas_da_rota(rota, barreiras_do_cadastro()):
        tocada = barreira.id in nomes_atingidos
        folium.GeoJson(
            barreira.geometria.__geo_interface__,
            style_function=lambda _, tocada=tocada: {
                "color": COR_BARREIRA,
                "weight": 5 if tocada else 2,
                "opacity": 0.9 if tocada else 0.35,
            },
            tooltip=f"{barreira.rotulo} ({barreira.tipo})",
        ).add_to(mapa)

    folium.PolyLine(
        [(lat, lon) for lon, lat in rota.linha.coords],
        color=COR_ROTA,
        weight=5,
        opacity=0.9,
        tooltip=f"Menor caminho a pé — {rota.distancia_m:,.0f} m".replace(",", "."),
    ).add_to(mapa)

    folium.Marker(
        (casa.lat, casa.lon), tooltip=f"A — {casa.endereco_formatado}", icon=folium.Icon(color="blue")
    ).add_to(mapa)
    folium.Marker(
        (escola.lat, escola.lon),
        tooltip=f"B — {escola.endereco_formatado}",
        icon=folium.Icon(color="green"),
    ).add_to(mapa)

    minx, miny, maxx, maxy = rota.linha.bounds
    mapa.fit_bounds([(miny, minx), (maxy, maxx)], padding=(30, 30))
    return mapa


# --------------------------------------------------------------------------- #
# Formulário de endereço
# --------------------------------------------------------------------------- #


def _formatar_opcao(local: Local) -> str:
    texto = local.endereco_formatado
    if local.adequacao is not None:
        texto = f"{texto} (compatibilidade {local.adequacao})"
    if local.numero_informado and not local.numero_confirmado:
        texto = f"{texto} — ⚠️ sem confirmação do nº {local.numero_informado}"
    return texto


def _aviso_numero_nao_confirmado(local: Local) -> None:
    if local.numero_informado and not local.numero_confirmado:
        st.warning(
            f"O sistema localizou a rua, mas **não confirmou o número {local.numero_informado}**. "
            "O pin pode cair no meio da via, não na porta — confira no mapa depois de calcular."
        )


def _fingerprint_calculo(
    casa: Local | None, escola: Local | None, escolheu: bool
) -> tuple:
    def _pin(local: Local | None) -> tuple | None:
        if local is None:
            return None
        return (local.endereco_formatado, round(local.lat, 6), round(local.lon, 6))

    return (_pin(casa), _pin(escola), escolheu)


def _limpar_resultado_se_entrada_mudou(
    casa: Local | None, escola: Local | None, escolheu: bool
) -> None:
    salvo = st.session_state.get("resultado_salvo")
    if not salvo:
        return
    if _fingerprint_calculo(casa, escola, escolheu) != salvo.get("fingerprint"):
        del st.session_state["resultado_salvo"]


def _status_integracoes() -> None:
    """Indicadores discretos de quais APIs estão configuradas."""
    google_ok = bool(ler_google_api_key())
    ors_ok = bool(_ler_api_key_ors())
    st.caption(
        f"{'✅' if google_ok else '⚠️'} Google Places (busca) · "
        f"{'✅' if ors_ok else '⚠️'} OpenRouteService (rotas)"
    )
    if not google_ok:
        st.caption("Configure `GOOGLE_MAPS_API_KEY` nos Secrets para buscar endereços.")
    if not ors_ok:
        st.caption("Sem chave ORS: cálculo de rota não funciona.")


def _expander_link_maps(chave: str) -> None:
    """Permite fixar endereço a partir de um link compartilhado do Google Maps."""
    with st.expander("Ou cole o link do Google Maps"):
        link = st.text_input(
            "Link compartilhado",
            key=f"{chave}_link",
            placeholder="https://maps.google.com/...",
        )
        if not link.strip():
            return
        coords = extrair_coordenadas_maps_url(link.strip())
        if not coords:
            st.warning("Não foi possível ler coordenadas deste link.")
            return
        lat, lon = coords
        try:
            exigir_coordenada_em_sao_paulo(lat, lon)
        except ErroExterno as e:
            st.error(str(e))
            return
        st.caption(f"Coordenadas do link: {lat:.6f}, {lon:.6f}")
        if st.button("Usar este pin do link", key=f"{chave}_usar_link"):
            st.session_state[f"{chave}_local"] = Local(
                texto_original=link.strip(),
                endereco_formatado=link.strip(),
                lat=lat,
                lon=lon,
                confianca=0.5,
                adequacao=40,
                numero_informado=None,
                numero_confirmado=False,
            )
            for suffix in ("_sel", "_sugestoes", "_texto_busca", "_place_id", "_texto_cache", "_candidatos"):
                st.session_state.pop(f"{chave}{suffix}", None)
            st.rerun()


def _exibir_local_confirmado(local: Local, chave: str) -> None:
    col_info, col_limpar = st.columns([5, 1])
    with col_info:
        st.success(f"Encontrado: **{local.endereco_formatado}**")
    with col_limpar:
        if st.button("Limpar", key=f"{chave}_limpar", help="Apagar este endereço"):
            for suffix in (
                "_local",
                "_sel",
                "_link",
                "_texto",
                "_sugestoes",
                "_texto_busca",
                "_place_id",
                "_texto_cache",
                "_candidatos",
                "_escolha",
                "_escolha_place",
            ):
                st.session_state.pop(f"{chave}{suffix}", None)
            st.rerun()
    _aviso_numero_nao_confirmado(local)
    st.caption(f"Coordenada: {local.lat:.6f}, {local.lon:.6f}")


def campo_endereco_busca_google(rotulo: str, chave: str, exemplo: str, api_key: str) -> Local | None:
    """Campo de texto nativo + sugestões Google Places (server-side)."""
    st.markdown(f"**{rotulo}**")
    texto = st.text_input(
        "Digite o endereço",
        key=f"{chave}_texto",
        placeholder=exemplo,
        help="Rua, número e bairro em São Paulo. Depois clique em **Buscar sugestões**.",
    )

    local_salvo = st.session_state.get(f"{chave}_local")
    texto_limpo = texto.strip()

    if texto_limpo and not local_salvo:
        buscar = st.button("Buscar sugestões", key=f"{chave}_buscar", type="secondary")
        cache_busca = f"{chave}_texto_busca"

        if buscar:
            try:
                consumir_geocodificacao()
            except ErroExterno as e:
                st.error(str(e))
                return None
            try:
                sugestoes = buscar_sugestoes_endereco(texto_limpo, api_key)
            except ErroExterno as e:
                st.error(str(e))
                st.caption(
                    "No Google Cloud, habilite **Places API (New)** ou **Geocoding API** "
                    "para a mesma chave usada em `GOOGLE_MAPS_API_KEY`."
                )
                return None
            st.session_state[f"{chave}_sugestoes"] = sugestoes
            st.session_state[cache_busca] = texto_limpo
            st.session_state.pop(f"{chave}_place_id", None)
            st.session_state.pop(f"{chave}_escolha_place", None)

        if st.session_state.get(cache_busca) != texto_limpo:
            st.session_state.pop(f"{chave}_sugestoes", None)
            st.session_state.pop(cache_busca, None)
            st.session_state.pop(f"{chave}_place_id", None)
        elif st.session_state.get(cache_busca) == texto_limpo:
            sugestoes = st.session_state.get(f"{chave}_sugestoes") or []
            if not sugestoes:
                st.warning(
                    "Nenhuma sugestão. Inclua número e bairro, ou cole o endereço "
                    "completo do Google Maps no campo acima."
                )
            else:
                opcoes = {s["id"]: s for s in sugestoes}
                escolha_id = st.radio(
                    "Escolha o endereço",
                    list(opcoes.keys()),
                    format_func=lambda sid: opcoes[sid]["texto"],
                    key=f"{chave}_escolha_place",
                    index=None,
                )
                if escolha_id:
                    if st.session_state.get(f"{chave}_place_id") != escolha_id:
                        escolhida = opcoes[escolha_id]
                        try:
                            if escolhida.get("local") is not None:
                                local = escolhida["local"]
                            else:
                                endereco = parse_endereco_maps(texto_limpo)
                                local = detalhes_place_id(
                                    escolhida["place_id"], api_key, texto_limpo, endereco
                                )
                            exigir_coordenada_em_sao_paulo(local.lat, local.lon)
                        except ErroExterno as e:
                            st.error(str(e))
                            return None
                        st.session_state[f"{chave}_place_id"] = escolha_id
                        st.session_state[f"{chave}_local"] = local
                    local_salvo = st.session_state.get(f"{chave}_local")

    if not local_salvo:
        _expander_link_maps(chave)
        st.caption(
            "Digite o endereço e clique em **Buscar sugestões**, "
            "ou use um link do Maps abaixo."
        )
        return None

    _exibir_local_confirmado(local_salvo, chave)
    _expander_link_maps(chave)
    return local_salvo


def campo_endereco_colado(rotulo: str, chave: str, exemplo: str) -> Local | None:
    """
    Devolve o `Local` confirmado, ou None enquanto não houver escolha confiável.

    O endereço formatado que o geocodificador entendeu é sempre exibido: um leigo
    bate o olho em "R. das Flores, 120 — Centro" e percebe na hora se o bairro veio
    errado, coisa que um pin sozinho no mapa não denuncia.
    """
    st.markdown(f"**{rotulo}**")
    texto = st.text_input(
        "Endereço completo (como no Google Maps)",
        key=f"{chave}_texto",
        placeholder=exemplo,
        help="Abra o endereço no Google Maps, copie a linha inteira e cole aqui. "
        "O padrão é: rua e número - bairro, São Paulo - SP, CEP.",
    )

    local_salvo = st.session_state.get(f"{chave}_local")
    if local_salvo:
        _exibir_local_confirmado(local_salvo, chave)
        _expander_link_maps(chave)
        return local_salvo

    if not texto.strip():
        _expander_link_maps(chave)
        return None

    endereco = parse_endereco_maps(texto)
    if not endereco.cep:
        st.warning(
            "Sem CEP no endereço colado. Copie a linha inteira do Google Maps — "
            "o CEP no final ajuda a cair no bairro certo."
        )
    elif not endereco.logradouro or not endereco.numero or not endereco.bairro:
        st.warning(
            "O formato não parece o do Google Maps. Use: "
            "rua, número - bairro, São Paulo - SP, CEP."
        )
    else:
        st.caption(
            f"Entendido como: **{endereco.logradouro}, {endereco.numero}** "
            f"— {endereco.bairro} — CEP {endereco.cep}"
        )

    if not (endereco.logradouro and endereco.numero and endereco.bairro and endereco.cep):
        return None

    cache_key = f"{chave}_candidatos"
    texto_normalizado = " ".join(texto.strip().split())
    buscar = st.button("Buscar endereço", key=f"{chave}_buscar", type="secondary")

    if buscar or st.session_state.get(f"{chave}_texto_cache") == texto_normalizado:
        if buscar:
            try:
                consumir_geocodificacao()
            except ErroExterno as e:
                st.error(str(e))
                return None
            try:
                candidatos = geocodificar(texto, _ler_api_key_ors())
            except ErroExterno as e:
                st.error(str(e))
                return None
            st.session_state[f"{chave}_texto_cache"] = texto_normalizado
            st.session_state[cache_key] = candidatos
        elif st.session_state.get(f"{chave}_texto_cache") == texto_normalizado:
            candidatos = st.session_state.get(cache_key, [])
        else:
            st.info("Clique em **Buscar endereço** para localizar no mapa.")
            return None
    else:
        st.info("Clique em **Buscar endereço** para localizar no mapa.")
        return None

    if not candidatos:
        st.error("Nenhum resultado para este endereço.")
        return None

    resolucao = resolver_geocodificacao(texto, candidatos)
    if resolucao.local and resolucao.automatico:
        escolhido = resolucao.local
        st.success(f"Encontrado: **{escolhido.endereco_formatado}**")
        _aviso_numero_nao_confirmado(escolhido)
    elif resolucao.opcoes:
        st.warning(
            "Não foi possível escolher sozinho com segurança. "
            "Selecione o endereço que bate com o Google Maps."
        )
        escolhido = st.radio(
            "Qual destes?",
            resolucao.opcoes,
            format_func=_formatar_opcao,
            key=f"{chave}_escolha",
            index=None,
        )
        if escolhido is None:
            st.info("Selecione um endereço na lista acima para continuar.")
            return None
        _aviso_numero_nao_confirmado(escolhido)
    else:
        st.error(
            "Nenhum resultado compatível com o endereço colado. "
            "Confira se copiou a linha inteira do Google Maps."
        )
        return None

    st.caption(f"Coordenada: {escolhido.lat:.6f}, {escolhido.lon:.6f}")
    _expander_link_maps(chave)
    return escolhido


def campo_endereco(rotulo: str, chave: str, exemplo: str) -> Local | None:
    api_key = ler_google_api_key()
    if api_key:
        return campo_endereco_busca_google(rotulo, chave, exemplo, api_key)
    return campo_endereco_colado(rotulo, chave, exemplo)


# --------------------------------------------------------------------------- #
# Página
# --------------------------------------------------------------------------- #


def pagina_principal() -> None:
    aplicar_estilo()
    marca()
    st.title("Elegibilidade a transporte escolar")
    lead(
        "A criança tem direito quando o menor caminho a pé até a escola encosta "
        "em alguma rua cadastrada como barreira. A rota é sempre a pé, nunca GPS de carro."
    )
    passos_consulta()

    with st.sidebar:
        sidebar_marca()
        st.markdown("**Cadastro de barreiras**")
        try:
            barreiras = barreiras_do_cadastro()
            nomes = sorted({b.nome for b in barreiras})
            st.metric("Ruas cadastradas", len(nomes))
            st.caption(f"{len(barreiras)} trechos no total")
            busca = st.text_input("Buscar no cadastro", key="busca_barreira", placeholder="Nome da via...")
            if busca.strip():
                filtradas = [b for b in barreiras if busca.lower() in b.rotulo.lower()][:25]
                for barreira in sorted(filtradas, key=lambda b: b.rotulo):
                    st.write(f"• {barreira.rotulo}")
                if len(filtradas) == 25:
                    st.caption("Mostrando no máximo 25 resultados — refine a busca.")
        except ErroExterno as e:
            st.error(str(e))
            st.stop()

        with st.expander("Ajuste técnico"):
            buffer_m = st.number_input(
                "Buffer da barreira (m)",
                min_value=1.0,
                max_value=50.0,
                value=BUFFER_M_PADRAO,
                step=1.0,
                help="Não mexa sem ter os casos conhecidos rodando. Buffer generoso demais "
                "faz a rota encostar em via que ela não usa.",
            )
        _status_integracoes()
        try:
            st.caption(f"Cadastro: {descricao_cadastro(ARQUIVO_BARREIRAS)}")
        except Exception:
            pass
        if usuario_e_admin():
            st.page_link("pages/1_Cadastro_de_barreiras.py", label="🛠️ Gerenciar barreiras")
        st.caption(
            "Endereços ficam na sessão do servidor até logout. "
            "Sem banco de dados nem histórico de consultas."
        )

    esquerda, direita = st.columns(2, gap="medium")
    with esquerda:
        with st.container(border=True):
            casa = campo_endereco("🏠 Endereço da casa", "casa", EXEMPLO_ENDERECO_MAPS)
    with direita:
        with st.container(border=True):
            escola = campo_endereco(
                "🏫 Endereço da escola",
                "escola",
                "Av. Rudge, 700 - Bom Retiro, São Paulo - SP, 01133-000",
            )

    with st.container(border=True):
        escolheu = st.checkbox(
            "A responsável escolheu esta escola",
            key="escolheu_escola",
            help="Quando a escola foi escolhida pela responsável, não há direito a transporte, "
            "independentemente do trajeto.",
        )
        _limpar_resultado_se_entrada_mudou(casa, escola, escolheu)
        calcular = st.button(
            "Calcular",
            type="primary",
            disabled=not (casa and escola),
            use_container_width=True,
        )
    if calcular and casa and escola:
        try:
            consumir_calculo()
        except ErroExterno as e:
            st.error(str(e))
            return
        fingerprint = _fingerprint_calculo(casa, escola, escolheu)
        try:
            if escolheu:
                resultado = decidir(None, [], escolheu_escola=True)
                st.session_state["resultado_salvo"] = {
                    "fingerprint": fingerprint,
                    "resultado": resultado,
                    "rota": None,
                    "casa": casa,
                    "escola": escola,
                    "atingidas": [],
                }
            else:
                with st.spinner("Calculando o menor caminho a pé..."):
                    rota = rota_a_pe(casa, escola, obter_api_key())
                atingidas = barreiras_atingidas(rota, barreiras, buffer_m)
                resultado = decidir(rota, atingidas, escolheu_escola=False)
                st.session_state["resultado_salvo"] = {
                    "fingerprint": fingerprint,
                    "resultado": resultado,
                    "rota": rota,
                    "casa": casa,
                    "escola": escola,
                    "atingidas": atingidas,
                }
        except ErroExterno as e:
            st.session_state.pop("resultado_salvo", None)
            st.error(f"{e}\n\nSem a rota não dá para decidir — isto **não** significa 'sem direito'.")
            return

    salvo = st.session_state.get("resultado_salvo")
    if not salvo:
        if not (casa and escola):
            st.info("Informe os dois endereços e confira o que o sistema encontrou.")
        return

    mostrar_resultado(salvo["resultado"])
    rota = salvo.get("rota")
    if rota is None:
        return

    with st.container(border=True):
        st.subheader("Trajeto")
        chips_mapa()
        st_folium(
            montar_mapa(rota, salvo["casa"], salvo["escola"], salvo["atingidas"]),
            height=520,
            use_container_width=True,
            returned_objects=[],
        )


def mostrar_resultado(resultado) -> None:
    veredito(resultado)
    st.markdown(f"**Motivo:** {resultado.motivo}")

    col_dist, col_vias = st.columns(2)
    with col_dist:
        if resultado.distancia_m is not None:
            st.metric("Distância a pé", f"{resultado.distancia_m:,.0f} m".replace(",", "."))
    with col_vias:
        if resultado.barreiras_atingidas:
            st.markdown("**Barreiras no caminho:**")
            for nome in resultado.barreiras_atingidas:
                st.markdown(f"- {nome}")


def main() -> None:
    exigir_login()
    pagina_principal()


if __name__ == "__main__":
    main()
