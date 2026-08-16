"""CRUD do cadastro de barreiras — página administrativa."""

from __future__ import annotations

import uuid
from pathlib import Path

import folium
import streamlit as st
from streamlit_folium import st_folium

from core.auth_app import exigir_admin
from core.barreiras import TIPOS_BARREIRA, Barreira
from core.barreiras_cache import invalidar_cache_barreiras, store_barreiras
from core.barreiras_osm import (
    aplicar_metadados,
    barreira_de_cliques,
    buscar_barreira_entre_links,
    buscar_barreiras_rua,
    clique_distinto,
    comprimento_m,
    extremos_preview,
    nome_via_de_entrada,
    refinar_preview,
)
from core.barreiras_store import descricao_store
from core.erros import ErroExterno
from core.rate_limit import consumir_busca_barreira_osm

ARQUIVO_BARREIRAS = Path(__file__).resolve().parent.parent / "dados" / "barreiras.geojson"
COR_BARREIRA = "#d1242f"
TIPOS_FORM = [t for t in TIPOS_BARREIRA if t != "(sem tipo)"]

st.set_page_config(page_title="Cadastro de barreiras", page_icon="🛠️", layout="wide")

exigir_admin()


@st.cache_resource(show_spinner=False)
def _store():
    return store_barreiras(ARQUIVO_BARREIRAS)


def _pino_letra(lat: float, lon: float, letra: str, cor: str) -> folium.Marker:
    return folium.Marker(
        [lat, lon],
        tooltip=letra,
        icon=folium.DivIcon(
            html=(
                f'<div style="font-size:12px;font-weight:700;color:#fff;'
                f"background:{cor};border-radius:10px;padding:1px 7px;"
                f'border:1px solid #fff">{letra}</div>'
            )
        ),
    )


def _mapa_preview(
    barreiras: list[Barreira],
    *,
    centro=None,
    zoom: int | None = None,
    cliques: list[tuple[float, float]] | None = None,
    mostrar_extremos: bool = True,
) -> folium.Map:
    mapa = folium.Map(
        location=centro or [-23.55, -46.63],
        tiles="cartodbpositron",
        control_scale=True,
        zoom_start=zoom or 14,
    )
    for i, barreira in enumerate(barreiras, start=1):
        folium.GeoJson(
            barreira.geometria.__geo_interface__,
            style_function=lambda _: {"color": COR_BARREIRA, "weight": 5, "opacity": 0.9},
            tooltip=f"{i}. {barreira.rotulo}",
        ).add_to(mapa)
        lon, lat = barreira.geometria.centroid.coords[0]
        folium.Marker(
            [lat, lon],
            tooltip=f"Trecho {i}",
            icon=folium.DivIcon(
                html=(
                    f'<div style="font-size:12px;font-weight:700;color:#fff;'
                    f'background:#d1242f;border-radius:10px;padding:1px 6px">{i}</div>'
                )
            ),
        ).add_to(mapa)
    extremos = extremos_preview(barreiras) if mostrar_extremos and barreiras else None
    if extremos and not cliques:
        _pino_letra(*extremos[0], "A", "#111827").add_to(mapa)
        _pino_letra(*extremos[1], "B", "#111827").add_to(mapa)
    for i, (lat, lon) in enumerate(cliques or [], start=1):
        letra = {1: "A", 2: "B", 3: "C"}.get(i, str(i))
        _pino_letra(lat, lon, letra, "#1d4ed8").add_to(mapa)
    if barreiras and not centro:
        minx, miny, maxx, maxy = barreiras[0].geometria.bounds
        for barreira in barreiras[1:]:
            bx0, by0, bx1, by1 = barreira.geometria.bounds
            minx, miny, maxx, maxy = min(minx, bx0), min(miny, by0), max(maxx, bx1), max(maxy, by1)
        mapa.fit_bounds([(miny, minx), (maxy, maxx)], padding=(30, 30))
    return mapa


def _limpar_formulario() -> None:
    for chave in (
        "editando_id",
        "preview_barreiras",
        "preview_entrada",
        "preview_rotulo",
        "preview_descartados",
        "preview_cliques",
        "preview_click_visto",
        "preview_modo_mapa",
        "preview_modo_visto",
        "preview_mapa_view",
        "preview_mapa_geracao",
        "form_nome",
        "form_link_ini",
        "form_link_fim",
        "form_entrada",
        "form_num_inicio",
        "form_num_fim",
        "form_paridade",
        "form_tipo",
    ):
        st.session_state.pop(chave, None)


def _iniciar_edicao(barreira: Barreira) -> None:
    st.session_state["editando_id"] = barreira.id
    st.session_state["form_nome"] = barreira.nome
    st.session_state["form_link_ini"] = ""
    st.session_state["form_link_fim"] = ""
    st.session_state["form_entrada"] = barreira.nome
    st.session_state["form_num_inicio"] = int(barreira.numero_inicio or 0)
    st.session_state["form_num_fim"] = int(barreira.numero_fim or 0)
    st.session_state["form_paridade"] = barreira.paridade or "ambos"
    tipo = barreira.tipo if barreira.tipo in TIPOS_FORM else "rua"
    st.session_state["form_tipo"] = tipo
    st.session_state["preview_barreiras"] = [barreira]
    st.session_state["preview_rotulo"] = barreira.rotulo
    _resetar_ajuste_mapa()


def _metadados_form() -> dict:
    return {
        "nome": st.session_state.get("form_nome") or None,
        "tipo": st.session_state.get("form_tipo"),
        "numero_inicio": int(st.session_state.get("form_num_inicio") or 0) or None,
        "numero_fim": int(st.session_state.get("form_num_fim") or 0) or None,
        "paridade": st.session_state.get("form_paridade") or "ambos",
    }


def _resetar_ajuste_mapa() -> None:
    st.session_state["preview_cliques"] = []
    st.session_state.pop("preview_click_visto", None)
    st.session_state["preview_mapa_geracao"] = int(st.session_state.get("preview_mapa_geracao") or 0) + 1


def _aplicar_preview(preview: list[Barreira], *, rotulo: str | None = None, descartados: int = 0) -> None:
    st.session_state["preview_barreiras"] = preview
    st.session_state["preview_rotulo"] = rotulo or (preview[0].rotulo if preview else "")
    st.session_state["preview_descartados"] = descartados
    _resetar_ajuste_mapa()


def _retracar_por_cliques(nome: str, cliques: list[tuple[float, float]]) -> None:
    try:
        consumir_busca_barreira_osm()
    except ErroExterno as e:
        st.error(str(e))
        return
    meta = _metadados_form()
    try:
        with st.spinner("Refazendo o eixo a pé…"):
            preview = barreira_de_cliques(
                nome,
                cliques,
                tipo=meta["tipo"],
                numero_inicio=meta["numero_inicio"],
                numero_fim=meta["numero_fim"],
                paridade=meta["paridade"],
            )
    except ErroExterno as e:
        st.error(str(e))
        return
    if not preview:
        st.error("Não deu para traçar com esses pontos. Clique de novo em cima da rua.")
        return
    _aplicar_preview(preview, rotulo=preview[0].rotulo)
    st.rerun()


def _secao_formulario() -> None:
    editando_id = st.session_state.get("editando_id")
    if editando_id:
        st.subheader(f"Editando: {st.session_state.get('preview_rotulo') or editando_id}")
        st.caption(
            "Ajuste nome, tipo e faixa, ou cole **dois links** (início e fim) "
            "para refazer o traçado — útil quando a linha cobriu só um pedaço da rua."
        )
    else:
        st.subheader("Nova barreira")
        st.caption(
            "Cole o link do **início** e do **fim** da rua (vale `maps.app.goo.gl`). "
            "O traçado segue o **eixo da via a pé**, nunca o GPS de carro. Confira no mapa antes de salvar."
        )

    st.session_state.setdefault("form_paridade", "ambos")
    st.session_state.setdefault("form_tipo", "rua")
    st.session_state.setdefault("form_num_inicio", 0)
    st.session_state.setdefault("form_num_fim", 0)

    nome = st.text_input(
        "Nome da via",
        key="form_nome",
        placeholder="Ex.: Rua Cruz de Malta",
    )

    st.markdown("**1. Traçado** — dois links (recomendado)")
    col_ini, col_fim = st.columns(2)
    with col_ini:
        link_ini = st.text_input(
            "Link do início",
            key="form_link_ini",
            placeholder="https://maps.app.goo.gl/…",
        )
    with col_fim:
        link_fim = st.text_input(
            "Link do fim",
            key="form_link_fim",
            placeholder="https://maps.app.goo.gl/…",
        )

    with st.expander("Ou um único link / endereço (rua inteira, menos preciso)"):
        entrada = st.text_input(
            "Link, endereço ou nome",
            key="form_entrada",
            placeholder="https://maps.app.goo.gl/…  ou  R. Cruz de Malta, São Paulo",
        )

    if st.button("Traçar no mapa", type="primary", key="form_tracar"):
        try:
            consumir_busca_barreira_osm()
        except ErroExterno as e:
            st.error(str(e))
            return
        meta = _metadados_form()
        try:
            with st.spinner("Traçando a via a pé…"):
                if link_ini.strip() and link_fim.strip():
                    preview = buscar_barreira_entre_links(
                        nome or entrada,
                        link_ini,
                        link_fim,
                        tipo=meta["tipo"],
                        numero_inicio=meta["numero_inicio"],
                        numero_fim=meta["numero_fim"],
                        paridade=meta["paridade"],
                    )
                elif (entrada or "").strip() or nome.strip():
                    preview = buscar_barreiras_rua(
                        (entrada or nome).strip(),
                        numero_inicio=meta["numero_inicio"],
                        numero_fim=meta["numero_fim"],
                        paridade=meta["paridade"],
                        tipo=meta["tipo"],
                    )
                else:
                    st.error("Cole os dois links (início e fim) ou um endereço/nome da rua.")
                    return
        except ErroExterno as e:
            st.error(str(e))
            return
        if nome.strip():
            aplicar_metadados(preview, nome=nome.strip())
        ancora_txt = (entrada or nome or link_ini or "").strip()
        preview, descartados = refinar_preview(preview, ancora_txt)
        if not preview:
            st.error(
                "Nenhum trecho ficou em São Paulo capital perto deste endereço. "
                "Use os dois links (início e fim) da rua certa."
            )
            return
        _aplicar_preview(preview, rotulo=preview[0].rotulo if preview else nome, descartados=descartados)
        st.rerun()

    preview: list[Barreira] | None = st.session_state.get("preview_barreiras")
    if not preview:
        if editando_id:
            st.info("A geometria atual está carregada. Salve os dados ou refaça o traçado com dois links.")
        return

    entendido = nome_via_de_entrada(nome or preview[0].nome) or preview[0].nome
    metros = sum(comprimento_m(b) for b in preview)
    st.success(f"Entendi **{entendido}** — {len(preview)} trecho(s), cerca de **{metros:.0f} m**.")
    descartados = int(st.session_state.get("preview_descartados") or 0)
    if descartados:
        st.caption(
            f"{descartados} trecho(s) de fora da capital (ou longe deste endereço) foram ignorados."
        )
    if metros < 80:
        st.warning(
            "Traçado curto: provavelmente pegou só um pedaço da rua. "
            "Cole o link do **início** e do **fim** e trace de novo."
        )
    if metros > 2500 and (meta_tipo := st.session_state.get("form_tipo")) == "rua":
        st.warning("Mais de 2,5 km para uma “rua”. Confira se o caminho não saiu da via.")

    st.markdown("**Trechos nesta prévia** — remova os que não são desta rua:")
    for i, barreira in enumerate(list(preview)):
        col_info, col_rm = st.columns([5, 1])
        with col_info:
            st.caption(f"**{i + 1}.** {barreira.rotulo} · ~{comprimento_m(barreira):.0f} m · {barreira.tipo}")
        with col_rm:
            if st.button("Remover", key=f"rm_prev_{barreira.id}_{i}", type="secondary"):
                resto = [b for j, b in enumerate(preview) if j != i]
                if not resto:
                    st.session_state["preview_barreiras"] = []
                    st.session_state.pop("preview_rotulo", None)
                else:
                    st.session_state["preview_barreiras"] = resto
                _resetar_ajuste_mapa()
                st.rerun()

    modos = ("Conferir", "Ajustar início/fim", "Desenhar no eixo")
    modo = st.radio(
        "No mapa",
        modos,
        horizontal=True,
        key="preview_modo_mapa",
        help="Conferir e remover já bastam na maioria das vezes. "
        "Ajuste os pinos se a vermelha saiu da rua. Desenhe só no último caso.",
    )
    if modo == "Ajustar início/fim":
        st.caption(
            "Clique o **início (A)** e o **fim (B)** em cima da rua. "
            "O eixo a pé refaz sozinho — como arrastar os extremos da vermelha."
        )
    elif modo == "Desenhar no eixo":
        st.caption(
            "Último caso: clique **2 ou 3 pontos** em cima do eixo da rua "
            "(curvas longas pedem o terceiro). Depois use o botão."
        )
    else:
        st.caption("Confira a linha vermelha. Remova acima o trecho que não é desta rua.")

    if st.session_state.get("preview_modo_visto") != modo:
        st.session_state["preview_modo_visto"] = modo
        if st.session_state.get("preview_cliques"):
            _resetar_ajuste_mapa()
            st.rerun()

    cliques: list[tuple[float, float]] = list(st.session_state.get("preview_cliques") or [])
    if modo != "Conferir":
        col_status, col_limpar = st.columns([4, 1])
        with col_status:
            if not cliques:
                st.caption("Próximo clique: **A** (início).")
            elif len(cliques) == 1:
                st.caption("Próximo clique: **B** (fim).")
            elif modo == "Desenhar no eixo":
                st.caption("Opcional: clique **C** no meio de uma curva, ou use os pontos.")
        with col_limpar:
            if st.button("Limpar cliques", key="preview_limpar_cliques"):
                _resetar_ajuste_mapa()
                st.rerun()
        if modo == "Desenhar no eixo" and len(cliques) >= 2:
            if st.button("Usar estes pontos", type="primary", key="preview_usar_cliques"):
                _retracar_por_cliques(nome or preview[0].nome, cliques)

    vista = st.session_state.get("preview_mapa_view") or {}
    geracao = int(st.session_state.get("preview_mapa_geracao") or 0)
    chave_mapa = f"preview_mapa_{geracao}_{modo}_{len(cliques)}_" + "-".join(b.id for b in preview)
    mapa_out = st_folium(
        _mapa_preview(
            preview,
            centro=vista.get("center"),
            zoom=vista.get("zoom"),
            cliques=cliques if modo != "Conferir" else None,
        ),
        width=None,
        height=420,
        key=chave_mapa,
        returned_objects=["last_clicked", "center", "zoom"],
    )
    if mapa_out:
        centro = mapa_out.get("center")
        if isinstance(centro, dict) and centro.get("lat") is not None:
            st.session_state["preview_mapa_view"] = {
                "center": [float(centro["lat"]), float(centro["lng"])],
                "zoom": int(mapa_out.get("zoom") or 14),
            }
        if modo != "Conferir":
            novo = clique_distinto(st.session_state.get("preview_click_visto"), mapa_out.get("last_clicked"))
            if novo:
                st.session_state["preview_click_visto"] = novo
                cliques.append(novo)
                st.session_state["preview_cliques"] = cliques[:3]
                if modo == "Ajustar início/fim" and len(cliques) >= 2:
                    _retracar_por_cliques(nome or preview[0].nome, cliques[:2])
                elif modo == "Desenhar no eixo" and len(cliques) >= 3:
                    _retracar_por_cliques(nome or preview[0].nome, cliques[:3])
                else:
                    st.rerun()

    st.markdown("**2. Ajustar** — tipo, faixa e paridade (não mudam o desenho)")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.number_input("Nº início", min_value=0, step=1, key="form_num_inicio", help="0 = sem faixa")
    with col2:
        st.number_input("Nº fim", min_value=0, step=1, key="form_num_fim")
    with col3:
        st.selectbox("Paridade", ["ambos", "par", "impar"], key="form_paridade")
    with col4:
        st.selectbox("Tipo da via", TIPOS_FORM, key="form_tipo")

    col_salvar, col_descartar = st.columns(2)
    with col_salvar:
        rotulo_btn = "Salvar alterações" if editando_id else "Cadastrar barreira"
        if st.button(rotulo_btn, type="primary", key="form_salvar"):
            meta = _metadados_form()
            aplicar_metadados(preview, **meta)
            store = _store()
            try:
                if editando_id:
                    atual = preview[0]
                    salva = Barreira(
                        id=editando_id,
                        nome=atual.nome,
                        tipo=atual.tipo,
                        geometria=atual.geometria,
                        numero_inicio=atual.numero_inicio,
                        numero_fim=atual.numero_fim,
                        paridade=atual.paridade,
                    )
                    store.atualizar(salva, mensagem=f"Cadastro: editar {salva.rotulo}")
                    invalidar_cache_barreiras()
                    _limpar_formulario()
                    st.success("Barreira atualizada.")
                    st.rerun()
                else:
                    criadas = 0
                    erros: list[str] = []
                    for barreira in preview:
                        try:
                            store.criar(barreira, mensagem=f"Cadastro: criar {barreira.rotulo}")
                            criadas += 1
                        except ErroExterno as e:
                            if "Já existe" in str(e):
                                nova = Barreira(
                                    id=f"{barreira.id}-{uuid.uuid4().hex[:6]}",
                                    nome=barreira.nome,
                                    tipo=barreira.tipo,
                                    geometria=barreira.geometria,
                                    numero_inicio=barreira.numero_inicio,
                                    numero_fim=barreira.numero_fim,
                                    paridade=barreira.paridade,
                                )
                                store.criar(nova, mensagem=f"Cadastro: criar {nova.rotulo}")
                                criadas += 1
                            else:
                                erros.append(str(e))
                    if criadas:
                        invalidar_cache_barreiras()
                        _limpar_formulario()
                        st.success(f"{criadas} trecho(s) cadastrado(s).")
                        st.rerun()
                    if erros:
                        st.error("\n".join(erros[:5]))
            except ErroExterno as e:
                st.error(str(e))
    with col_descartar:
        if st.button("Cancelar", key="form_cancelar"):
            _limpar_formulario()
            st.rerun()


store = _store()

st.title("🛠️ Cadastro de barreiras")
st.caption(
    "Cadastre ou edite ruas-barreira. Traçado **a pé** pelo eixo da via. "
    "Confira no mapa, remova trecho extra, ajuste início/fim ou desenhe 2–3 cliques no eixo."
)
st.info(f"Armazenamento: **{descricao_store(store)}**")

_secao_formulario()

st.divider()

try:
    barreiras = store.listar()
except ErroExterno as e:
    st.error(str(e))
    st.stop()

st.subheader(f"{len(barreiras)} trechos cadastrados")
for barreira in sorted(barreiras, key=lambda b: b.rotulo):
    with st.expander(barreira.rotulo):
        st.caption(f"ID: `{barreira.id}` · tipo: {barreira.tipo}")
        if barreira.numero_inicio or barreira.numero_fim:
            st.caption(
                f"Faixa: nº {barreira.numero_inicio or '…'} – {barreira.numero_fim or '…'}"
                f"{f' ({barreira.paridade})' if barreira.paridade else ''}"
            )
        st.caption(f"Comprimento: ~{comprimento_m(barreira):.0f} m")
        st_folium(_mapa_preview([barreira]), width=None, height=260, key=f"mapa_{barreira.id}")
        col_ed, col_rm = st.columns(2)
        with col_ed:
            if st.button("Editar", key=f"edit_{barreira.id}"):
                _iniciar_edicao(barreira)
                st.rerun()
        with col_rm:
            if st.button("Remover", key=f"del_{barreira.id}", type="secondary"):
                try:
                    store.remover(barreira.id, mensagem=f"Cadastro: remover {barreira.rotulo}")
                    invalidar_cache_barreiras()
                    if st.session_state.get("editando_id") == barreira.id:
                        _limpar_formulario()
                    st.success("Barreira removida.")
                    st.rerun()
                except ErroExterno as e:
                    st.error(str(e))
