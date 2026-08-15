"""
Interface do app de elegibilidade a transporte escolar — São Paulo capital.

Protótipo de validação da regra. NÃO PERSISTE NADA: sem log, sem histórico, sem
analytics. Os endereços vivem só na sessão do navegador de quem está usando.

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
    carregar_barreiras,
    proximas_da_rota,
)
from core.decisao import decidir
from core.erros import ErroExterno
from core.geocode import EXEMPLO_ENDERECO_MAPS, Local, candidatos_ambiguos, geocodificar, parse_endereco_maps
from core.routing import Rota, rota_a_pe

ARQUIVO_BARREIRAS = Path(__file__).parent / "dados" / "barreiras.geojson"

COR_ROTA = "#1f6feb"
COR_BARREIRA = "#d1242f"

st.set_page_config(page_title="Transporte escolar — elegibilidade", page_icon="🚌", layout="wide")


# --------------------------------------------------------------------------- #
# Recursos
# --------------------------------------------------------------------------- #


@st.cache_resource(show_spinner="Carregando o cadastro de barreiras...")
def barreiras_do_cadastro() -> list[Barreira]:
    """
    Carregado uma vez por processo. `cache_resource` guarda o CADASTRO, que é
    público e versionado no Git — nada de dado pessoal entra aqui.
    """
    return carregar_barreiras(ARQUIVO_BARREIRAS)


def obter_api_key() -> str:
    """
    No Streamlit Cloud a chave vem de Settings → Secrets; local, da variável de
    ambiente. `st.secrets` estoura quando não há arquivo nenhum, daí o try.
    """
    try:
        if "ORS_API_KEY" in st.secrets:
            return str(st.secrets["ORS_API_KEY"]).strip()
    except Exception:
        pass
    chave = os.environ.get("ORS_API_KEY", "").strip()
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
            tooltip=f"{barreira.nome} ({barreira.tipo})",
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


def campo_endereco(rotulo: str, chave: str, exemplo: str) -> Local | None:
    """
    Devolve o `Local` confirmado, ou None enquanto não houver escolha.

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

    if not texto.strip():
        return None

    _, cep = parse_endereco_maps(texto)
    if not cep:
        st.warning(
            "Sem CEP no endereço colado. Copie a linha inteira do Google Maps — "
            "o CEP no final ajuda a cair no bairro certo."
        )

    try:
        candidatos = geocodificar(texto, obter_api_key())
    except ErroExterno as e:
        st.error(str(e))
        return None

    ambiguos = candidatos_ambiguos(candidatos)
    if ambiguos:
        st.warning(
            f"{len(ambiguos) + 1} endereços com pontuação parecida. "
            "Escolha o que bate com o Google Maps."
        )
        opcoes = [candidatos[0], *ambiguos]
        escolhido = st.radio(
            "Qual destes?",
            opcoes,
            format_func=lambda local: local.endereco_formatado,
            key=f"{chave}_escolha",
        )
    else:
        escolhido = candidatos[0]
        st.success(f"Encontrado: **{escolhido.endereco_formatado}**")

    st.caption(f"Coordenada: {escolhido.lat:.6f}, {escolhido.lon:.6f}")
    return escolhido


# --------------------------------------------------------------------------- #
# Página
# --------------------------------------------------------------------------- #


def main() -> None:
    st.title("🚌 Elegibilidade a transporte escolar")
    st.caption(
        "Município de São Paulo. Cole os endereços como no Google Maps. "
        "A criança tem direito quando o menor caminho a pé até a escola encosta "
        "em alguma rua cadastrada como barreira."
    )

    with st.sidebar:
        st.subheader("Cadastro de barreiras")
        try:
            barreiras = barreiras_do_cadastro()
            nomes = sorted({b.nome for b in barreiras})
            st.metric("Ruas cadastradas", len(nomes))
            st.caption(f"{len(barreiras)} trechos no total")
            for nome in nomes:
                st.write(f"• {nome}")
        except ErroExterno as e:
            st.error(str(e))
            st.stop()

        st.divider()
        buffer_m = st.number_input(
            "Buffer da barreira (m)",
            min_value=1.0,
            max_value=50.0,
            value=BUFFER_M_PADRAO,
            step=1.0,
            help="Não mexa sem ter os casos conhecidos rodando. Buffer generoso demais "
            "faz a rota encostar em via que ela não usa.",
        )
        st.divider()
        st.caption(
            "Protótipo de validação da regra. Nenhuma consulta é gravada: sem log, "
            "sem histórico, sem analytics."
        )

    esquerda, direita = st.columns(2)
    with esquerda:
        casa = campo_endereco("🏠 Endereço da casa", "casa", EXEMPLO_ENDERECO_MAPS)
    with direita:
        escola = campo_endereco(
            "🏫 Endereço da escola",
            "escola",
            "Av. Rudge, 700 - Bom Retiro, São Paulo - SP, 01133-000",
        )

    st.divider()
    escolheu = st.checkbox(
        "A responsável escolheu esta escola",
        help="Quando a escola foi escolhida pela responsável, não há direito a transporte, "
        "independentemente do trajeto.",
    )

    calcular = st.button("Calcular", type="primary", disabled=not (casa and escola))
    if not calcular:
        if not (casa and escola):
            st.info("Informe os dois endereços e confira o que o sistema encontrou.")
        return

    # A flag encerra a análise antes de gastar chamada de rota.
    if escolheu:
        resultado = decidir(None, [], escolheu_escola=True)
        mostrar_resultado(resultado)
        return

    try:
        with st.spinner("Calculando o menor caminho a pé..."):
            rota = rota_a_pe(casa, escola, obter_api_key())
        atingidas = barreiras_atingidas(rota, barreiras, buffer_m)
    except ErroExterno as e:
        st.error(f"{e}\n\nSem a rota não dá para decidir — isto **não** significa 'sem direito'.")
        return

    resultado = decidir(rota, atingidas, escolheu_escola=False)
    mostrar_resultado(resultado)

    st.subheader("Trajeto")
    st.caption(
        "Rota em azul, barreiras em vermelho (traço grosso = tocada), "
        "A = casa, B = escola."
    )
    st_folium(montar_mapa(rota, casa, escola, atingidas), height=520, use_container_width=True)


def mostrar_resultado(resultado) -> None:
    if resultado.tem_direito:
        st.success("## ✅ COM DIREITO")
    else:
        st.error("## ❌ SEM DIREITO")

    st.markdown(f"**Motivo:** {resultado.motivo}")

    if resultado.distancia_m is not None:
        st.metric("Distância a pé", f"{resultado.distancia_m:,.0f} m".replace(",", "."))

    if resultado.barreiras_atingidas:
        st.markdown("**Barreiras no caminho:**")
        for nome in resultado.barreiras_atingidas:
            st.markdown(f"- {nome}")


if __name__ == "__main__":
    main()
