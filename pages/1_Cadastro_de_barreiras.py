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
    buscar_barreira_entre_pontos,
    buscar_barreiras_rua,
    nome_via_de_entrada,
)
from core.barreiras_store import descricao_store
from core.erros import ErroExterno
from core.google_geo import buscar_sugestoes_endereco, ler_google_api_key, parece_link_maps
from core.rate_limit import consumir_busca_barreira_osm

ARQUIVO_BARREIRAS = Path(__file__).resolve().parent.parent / "dados" / "barreiras.geojson"
COR_BARREIRA = "#d1242f"

st.set_page_config(page_title="Cadastro de barreiras", page_icon="🛠️", layout="wide")

exigir_admin()


@st.cache_resource(show_spinner=False)
def _store():
    return store_barreiras(ARQUIVO_BARREIRAS)


def _mapa_preview(barreiras: list[Barreira]) -> folium.Map:
    mapa = folium.Map(tiles="cartodbpositron", control_scale=True)
    for barreira in barreiras:
        folium.GeoJson(
            barreira.geometria.__geo_interface__,
            style_function=lambda _: {"color": COR_BARREIRA, "weight": 5, "opacity": 0.9},
            tooltip=barreira.rotulo,
        ).add_to(mapa)
    if barreiras:
        minx, miny, maxx, maxy = barreiras[0].geometria.bounds
        for barreira in barreiras[1:]:
            bx0, by0, bx1, by1 = barreira.geometria.bounds
            minx, miny, maxx, maxy = min(minx, bx0), min(miny, by0), max(maxx, bx1), max(maxy, by1)
        mapa.fit_bounds([(miny, minx), (maxy, maxx)], padding=(30, 30))
    return mapa


def _limpar_preview() -> None:
    for chave in ("preview_barreiras", "preview_entrada", "preview_rotulo"):
        st.session_state.pop(chave, None)


def _secao_nova_barreira() -> None:
    st.subheader("Nova barreira")
    st.caption(
        "Cole o **link do Google Maps** da rua (ou o endereço). "
        "Depois ajuste só o **nº início/fim**, a **paridade** e o **tipo**. "
        "Números em 0 = rua inteira."
    )

    pendente = st.session_state.pop("_nova_aplicar_sugestao", None)
    if pendente:
        st.session_state["nova_entrada"] = pendente
        st.session_state.pop("nova_sugestoes", None)

    entrada = st.text_input(
        "Link do Google Maps, endereço ou nome da rua",
        key="nova_entrada",
        placeholder="https://maps.app.goo.gl/…  ou  R. Cruz de Malta, São Paulo",
        help="Cole o link compartilhado do Maps, o endereço completo ou só o nome da via.",
    )

    api_key = ler_google_api_key()
    if api_key and entrada.strip() and not parece_link_maps(entrada):
        if st.button("Buscar sugestões de endereço", key="nova_google", type="secondary"):
            try:
                st.session_state["nova_sugestoes"] = buscar_sugestoes_endereco(entrada.strip(), api_key)
            except ErroExterno as e:
                st.error(str(e))
        sugestoes = st.session_state.get("nova_sugestoes") or []
        if sugestoes:
            st.caption("Sugestões (opcional) — clique para usar no campo acima:")
            for indice, sug in enumerate(sugestoes):
                if st.button(sug["texto"], key=f"nova_sug_btn_{indice}", type="secondary"):
                    st.session_state["_nova_aplicar_sugestao"] = sug["texto"]
                    st.rerun()

    col1, col2, col3 = st.columns(3)
    with col1:
        numero_inicio = st.number_input(
            "Nº início (opcional)",
            min_value=0,
            value=0,
            step=1,
            key="nova_num_inicio",
            help="0 = não limitar por número.",
        )
    with col2:
        numero_fim = st.number_input(
            "Nº fim (opcional)",
            min_value=0,
            value=0,
            step=1,
            key="nova_num_fim",
        )
    with col3:
        paridade = st.selectbox(
            "Paridade",
            ["", "ambos", "par", "impar"],
            key="nova_paridade",
        )

    tipos_opcao = ["(detectar automaticamente)", *TIPOS_BARREIRA]
    tipo = st.selectbox("Tipo da via", tipos_opcao, key="nova_tipo")

    if st.button("Buscar rua no mapa", type="primary", key="nova_buscar_osm"):
        if not entrada.strip():
            st.error("Cole o link do Google Maps ou o nome da rua.")
        else:
            try:
                consumir_busca_barreira_osm()
            except ErroExterno as e:
                st.error(str(e))
            else:
                try:
                    with st.spinner("Buscando traçado no mapa…"):
                        preview = buscar_barreiras_rua(
                            entrada,
                            numero_inicio=int(numero_inicio) or None,
                            numero_fim=int(numero_fim) or None,
                            paridade=paridade or None,
                            tipo=tipo,
                        )
                except ErroExterno as e:
                    st.error(str(e))
                else:
                    st.session_state["preview_barreiras"] = preview
                    st.session_state["preview_entrada"] = entrada.strip()
                    nome = nome_via_de_entrada(entrada)
                    if preview:
                        st.session_state["preview_rotulo"] = preview[0].rotulo
                    else:
                        st.session_state["preview_rotulo"] = nome

    with st.expander("Ou marque início e fim no mapa", expanded=False):
        st.caption(
            "Clique no **início** e depois no **fim** da barreira. "
            "O sistema traça o caminho de carro entre os dois pontos."
        )
        pontos = st.session_state.setdefault("desenho_pontos", [])
        mapa_desenho = folium.Map(
            location=[-23.48, -46.60],
            zoom_start=13,
            tiles="cartodbpositron",
            control_scale=True,
        )
        for i, (lat, lon) in enumerate(pontos):
            folium.Marker(
                [lat, lon],
                tooltip="Início" if i == 0 else "Fim",
            ).add_to(mapa_desenho)
        if len(pontos) == 2:
            folium.PolyLine(pontos, color=COR_BARREIRA, weight=4).add_to(mapa_desenho)
        clique = st_folium(mapa_desenho, width=None, height=360, key="mapa_desenho")
        last = (clique or {}).get("last_clicked") or {}
        if last.get("lat") is not None and last.get("lng") is not None:
            novo = (round(float(last["lat"]), 6), round(float(last["lng"]), 6))
            if not pontos or pontos[-1] != novo:
                if len(pontos) >= 2:
                    pontos.clear()
                pontos.append(novo)
                st.rerun()
        if pontos:
            st.caption(" · ".join(
                f"{'Início' if i == 0 else 'Fim'}: {lat:.5f}, {lon:.5f}"
                for i, (lat, lon) in enumerate(pontos)
            ))
        col_tracar, col_limpar_pts = st.columns(2)
        with col_tracar:
            if st.button("Traçar barreira entre os pontos", key="nova_tracar_cliques"):
                if len(pontos) < 2:
                    st.error("Clique em dois pontos no mapa (início e fim).")
                elif not entrada.strip():
                    st.error("Informe o nome da rua no campo acima.")
                else:
                    try:
                        consumir_busca_barreira_osm()
                        with st.spinner("Traçando caminho no Google Maps…"):
                            preview = buscar_barreira_entre_pontos(
                                entrada,
                                pontos[0],
                                pontos[1],
                                tipo=tipo,
                                numero_inicio=int(numero_inicio) or None,
                                numero_fim=int(numero_fim) or None,
                                paridade=paridade or None,
                            )
                    except ErroExterno as e:
                        st.error(str(e))
                    else:
                        st.session_state["preview_barreiras"] = preview
                        st.session_state["preview_entrada"] = entrada.strip()
                        st.session_state["preview_rotulo"] = preview[0].rotulo if preview else entrada
                        st.rerun()
        with col_limpar_pts:
            if st.button("Limpar pontos", key="nova_limpar_cliques"):
                st.session_state["desenho_pontos"] = []
                st.rerun()

    preview: list[Barreira] | None = st.session_state.get("preview_barreiras")
    if preview:
        st.success(
            f"**{len(preview)} trecho(s)** encontrado(s) para "
            f"**{st.session_state.get('preview_rotulo', '')}**. Confira no mapa."
        )
        st_folium(_mapa_preview(preview), width=None, height=400, key="preview_mapa")
        with st.expander("Detalhes dos trechos"):
            for barreira in preview[:40]:
                st.caption(f"· {barreira.rotulo} — tipo: {barreira.tipo}")
            if len(preview) > 40:
                st.caption(f"… e mais {len(preview) - 40} trechos.")

        col_salvar, col_limpar = st.columns(2)
        with col_salvar:
            if st.button("Cadastrar barreira(s)", type="primary", key="nova_confirmar"):
                store = _store()
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
                            try:
                                store.criar(nova, mensagem=f"Cadastro: criar {nova.rotulo}")
                                criadas += 1
                            except ErroExterno as e2:
                                erros.append(str(e2))
                        else:
                            erros.append(str(e))
                if criadas:
                    invalidar_cache_barreiras()
                    _limpar_preview()
                    st.success(f"{criadas} trecho(s) cadastrado(s).")
                    st.rerun()
                if erros:
                    st.error("\n".join(erros[:5]))
        with col_limpar:
            if st.button("Descartar prévia", key="nova_descartar"):
                _limpar_preview()
                st.rerun()


store = _store()

st.title("🛠️ Cadastro de barreiras")
st.caption(
    "Cadastre ruas que funcionam como barreira física. "
    "Cole o link do Google Maps e ajuste número, paridade e tipo."
)
st.info(f"Armazenamento: **{descricao_store(store)}**")

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
        st_folium(_mapa_preview([barreira]), width=None, height=260, key=f"mapa_{barreira.id}")
        if st.button("Remover", key=f"del_{barreira.id}", type="secondary"):
            try:
                store.remover(barreira.id, mensagem=f"Cadastro: remover {barreira.rotulo}")
                invalidar_cache_barreiras()
                st.success("Barreira removida.")
                st.rerun()
            except ErroExterno as e:
                st.error(str(e))

st.divider()
_secao_nova_barreira()
