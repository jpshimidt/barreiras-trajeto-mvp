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
    buscar_barreira_entre_links,
    buscar_barreiras_rua,
    comprimento_m,
    nome_via_de_entrada,
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


def _mapa_preview(barreiras: list[Barreira], *, centro=None) -> folium.Map:
    mapa = folium.Map(
        location=centro or [-23.55, -46.63],
        tiles="cartodbpositron",
        control_scale=True,
        zoom_start=14,
    )
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


def _limpar_formulario() -> None:
    for chave in (
        "editando_id",
        "preview_barreiras",
        "preview_entrada",
        "preview_rotulo",
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


def _metadados_form() -> dict:
    return {
        "nome": st.session_state.get("form_nome") or None,
        "tipo": st.session_state.get("form_tipo"),
        "numero_inicio": int(st.session_state.get("form_num_inicio") or 0) or None,
        "numero_fim": int(st.session_state.get("form_num_fim") or 0) or None,
        "paridade": st.session_state.get("form_paridade") or "ambos",
    }


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
            "O jeito mais fiel: cole o link do **início** e do **fim** da rua no Google Maps. "
            "O sistema traça o caminho entre os dois pins. Confira no mapa antes de salvar."
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
            with st.spinner("Traçando a via…"):
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
        st.session_state["preview_barreiras"] = preview
        st.session_state["preview_rotulo"] = preview[0].rotulo if preview else nome
        st.rerun()

    preview: list[Barreira] | None = st.session_state.get("preview_barreiras")
    if not preview:
        if editando_id:
            st.info("A geometria atual está carregada. Salve os dados ou refaça o traçado com dois links.")
        return

    entendido = nome_via_de_entrada(nome or preview[0].nome) or preview[0].nome
    metros = sum(comprimento_m(b) for b in preview)
    st.success(f"Entendi **{entendido}** — {len(preview)} trecho(s), cerca de **{metros:.0f} m**.")
    if metros < 80:
        st.warning(
            "Traçado curto: provavelmente pegou só um pedaço da rua. "
            "Cole o link do **início** e do **fim** e trace de novo."
        )
    if metros > 2500 and (meta_tipo := st.session_state.get("form_tipo")) == "rua":
        st.warning("Mais de 2,5 km para uma “rua”. Confira se o caminho não saiu da via.")

    st_folium(_mapa_preview(preview), width=None, height=400, key="preview_mapa")

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
    "Cadastre ou edite ruas-barreira. "
    "O traçado mais fiel vem de **dois links** do Google Maps (início e fim da via)."
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
