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
    clique_proximo,
    colar_clique_na_via,
    comprimento_m,
    extremos_preview,
    nome_via_de_entrada,
    refinar_preview,
)
from core.barreiras_store import descricao_store
from core.erros import ErroExterno
from core.rate_limit import consumir_busca_barreira_osm
from core.ui import aplicar_estilo, marca

ARQUIVO_BARREIRAS = Path(__file__).resolve().parent.parent / "dados" / "barreiras.geojson"
COR_BARREIRA = "#d1242f"
TIPOS_FORM = [t for t in TIPOS_BARREIRA if t != "(sem tipo)"]

st.set_page_config(page_title="Cadastro de barreiras", page_icon="🛠️", layout="wide")

exigir_admin()
aplicar_estilo()


@st.cache_resource(show_spinner=False)
def _store():
    return store_barreiras(ARQUIVO_BARREIRAS)


def _pino_letra(lat: float, lon: float, letra: str, cor: str) -> folium.Marker:
    return folium.Marker(
        [lat, lon],
        tooltip=letra,
        icon=folium.DivIcon(
            html=(
                f'<div style="font-size:15px;font-weight:800;color:#fff;'
                f"background:{cor};border-radius:14px;padding:3px 9px;"
                f'border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.45)">{letra}</div>'
            )
        ),
    )


def _grupo_preview(
    barreiras: list[Barreira],
    *,
    cliques: list[tuple[float, float]] | None = None,
    mostrar_extremos: bool = False,
) -> folium.FeatureGroup:
    """Linha vermelha + pinos — vai no FeatureGroup para o mapa não remountar."""
    grupo = folium.FeatureGroup(name="preview")
    for i, barreira in enumerate(barreiras, start=1):
        folium.GeoJson(
            barreira.geometria.__geo_interface__,
            style_function=lambda _: {"color": COR_BARREIRA, "weight": 7, "opacity": 0.9},
            tooltip=f"{i}. {barreira.rotulo}",
        ).add_to(grupo)
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
        ).add_to(grupo)
    pontos: list[tuple[tuple[float, float], str, str]] = []
    if cliques:
        for i, par in enumerate(cliques, start=1):
            letra = {1: "A", 2: "B", 3: "C"}.get(i, str(i))
            pontos.append((par, letra, "#1d4ed8"))
    elif mostrar_extremos:
        extremos = extremos_preview(barreiras)
        if extremos:
            pontos.append((extremos[0], "A", "#111827"))
            pontos.append((extremos[1], "B", "#111827"))
    for (lat, lon), letra, cor in pontos:
        folium.CircleMarker(
            [lat, lon],
            radius=11,
            color="#fff",
            weight=2,
            fill=True,
            fill_color=cor,
            fill_opacity=0.95,
            tooltip=letra,
        ).add_to(grupo)
        _pino_letra(lat, lon, letra, cor).add_to(grupo)
    return grupo


def _mapa_preview(
    barreiras: list[Barreira],
    *,
    centro=None,
    zoom: int | None = None,
    detalhado: bool = False,
) -> folium.Map:
    mapa = folium.Map(
        location=centro or [-23.55, -46.63],
        tiles=None if detalhado else "cartodbpositron",
        control_scale=True,
        zoom_start=zoom or 16,
    )
    if detalhado:
        folium.TileLayer("OpenStreetMap", name="Ruas (nomes)").add_to(mapa)
        folium.TileLayer(
            tiles=(
                "https://server.arcgisonline.com/ArcGIS/rest/services/"
                "World_Imagery/MapServer/tile/{z}/{y}/{x}"
            ),
            attr="Esri",
            name="Satélite",
        ).add_to(mapa)
        folium.LayerControl(collapsed=True, position="topright").add_to(mapa)
        mapa.get_root().header.add_child(
            folium.Element("<style>.leaflet-container{cursor:crosshair!important}</style>")
        )
    if not detalhado:
        for i, barreira in enumerate(barreiras, start=1):
            folium.GeoJson(
                barreira.geometria.__geo_interface__,
                style_function=lambda _: {"color": COR_BARREIRA, "weight": 7, "opacity": 0.9},
                tooltip=f"{i}. {barreira.rotulo}",
            ).add_to(mapa)
    if barreiras and not centro:
        minx, miny, maxx, maxy = barreiras[0].geometria.bounds
        for barreira in barreiras[1:]:
            bx0, by0, bx1, by1 = barreira.geometria.bounds
            minx, miny, maxx, maxy = min(minx, bx0), min(miny, by0), max(maxx, bx1), max(maxy, by1)
        mapa.fit_bounds([(miny, minx), (maxy, maxx)], padding=(40, 40))
    return mapa


def _limpar_formulario() -> None:
    for chave in (
        "editando_id",
        "preview_barreiras",
        "preview_entrada",
        "preview_rotulo",
        "preview_descartados",
        "preview_cliques",
        "preview_cliques_crus",
        "preview_click_visto",
        "preview_modo_mapa",
        "preview_modo_visto",
        "preview_mapa_view",
        "preview_mapa_geracao",
        "preview_forcar_conferir",
        "preview_zoom_rua",
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
    st.session_state.pop("preview_mapa_view", None)
    st.session_state["preview_forcar_conferir"] = True
    _resetar_ajuste_mapa()


def _metadados_form() -> dict:
    return {
        "nome": st.session_state.get("form_nome") or None,
        "tipo": st.session_state.get("form_tipo"),
        "numero_inicio": int(st.session_state.get("form_num_inicio") or 0) or None,
        "numero_fim": int(st.session_state.get("form_num_fim") or 0) or None,
        "paridade": st.session_state.get("form_paridade") or "ambos",
    }


def _limpar_cliques() -> None:
    """Tira os pinos sem remountar o mapa — o zoom que você fez fica."""
    st.session_state["preview_cliques"] = []
    st.session_state["preview_cliques_crus"] = []
    st.session_state.pop("preview_click_visto", None)


def _resetar_ajuste_mapa() -> None:
    _limpar_cliques()
    st.session_state["preview_mapa_geracao"] = int(st.session_state.get("preview_mapa_geracao") or 0) + 1
    st.session_state.pop("preview_zoom_rua", None)


def _aplicar_preview(
    preview: list[Barreira],
    *,
    rotulo: str | None = None,
    descartados: int = 0,
    manter_vista: bool = False,
) -> None:
    st.session_state["preview_barreiras"] = preview
    st.session_state["preview_rotulo"] = rotulo or (preview[0].rotulo if preview else "")
    st.session_state["preview_descartados"] = descartados
    if manter_vista:
        _limpar_cliques()
    else:
        _resetar_ajuste_mapa()
        st.session_state.pop("preview_mapa_view", None)
        st.session_state["preview_forcar_conferir"] = True


def _retracar_por_cliques(nome: str, cliques: list[tuple[float, float]]) -> None:
    try:
        consumir_busca_barreira_osm()
    except ErroExterno as e:
        st.error(str(e))
        _limpar_cliques()
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
        _limpar_cliques()
        return
    if not preview:
        st.error("Não deu para traçar com esses pontos. Clique de novo em cima da rua.")
        _limpar_cliques()
        return
    _aplicar_preview(preview, rotulo=preview[0].rotulo, manter_vista=True)
    st.rerun()


def _secao_formulario() -> None:
    if st.session_state.pop("preview_forcar_conferir", False):
        st.session_state["preview_modo_mapa"] = "Conferir"
        st.session_state["preview_modo_visto"] = "Conferir"

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
            "Dê **zoom** (scroll ou +/−) até ver o nome da rua. "
            "Clique perto do asfalto — o ponto gruda na via, não precisa acertar o pixel. "
            "A = início, B = fim."
        )
    elif modo == "Desenhar no eixo":
        st.caption(
            "Zoom na rua, depois 2 ou 3 cliques no asfalto (o terceiro só se curvar). "
            "O ponto gruda na via. Troque para **Satélite** no canto do mapa se ajudar."
        )
    else:
        st.caption("Confira a linha vermelha. Remova acima o trecho que não é desta rua.")

    if st.session_state.get("preview_modo_visto") != modo:
        st.session_state["preview_modo_visto"] = modo
        if st.session_state.get("preview_cliques"):
            _limpar_cliques()
            st.rerun()

    cliques: list[tuple[float, float]] = list(st.session_state.get("preview_cliques") or [])
    if modo != "Conferir":
        col_status, col_desfazer, col_limpar = st.columns([3, 1, 1])
        with col_status:
            if not cliques:
                st.caption("Próximo: **A** (início da rua).")
            elif len(cliques) == 1:
                st.caption("A marcado. Próximo: **B** (fim da rua).")
            elif modo == "Desenhar no eixo":
                st.caption("A e B marcados. Opcional: **C** numa curva, ou use os pontos.")
        with col_desfazer:
            if cliques and st.button("Desfazer", key="preview_desfazer_clique"):
                cliques.pop()
                crus = list(st.session_state.get("preview_cliques_crus") or [])
                cru_desfeito = crus.pop() if crus else None
                st.session_state["preview_cliques"] = cliques
                st.session_state["preview_cliques_crus"] = crus
                if cru_desfeito:
                    st.session_state["preview_click_visto"] = cru_desfeito
                st.rerun()
        with col_limpar:
            if st.button("Limpar pinos", key="preview_limpar_cliques"):
                _limpar_cliques()
                st.rerun()
        if modo == "Desenhar no eixo" and len(cliques) >= 2:
            if st.button("Usar estes pontos", type="primary", key="preview_usar_cliques"):
                _retracar_por_cliques(nome or preview[0].nome, cliques)

    zoom_forcar = None
    if modo != "Conferir" and not st.session_state.get("preview_zoom_rua"):
        st.session_state["preview_zoom_rua"] = True
        zoom_forcar = 17
    elif modo == "Conferir":
        st.session_state.pop("preview_zoom_rua", None)

    geracao = int(st.session_state.get("preview_mapa_geracao") or 0)
    chave_mapa = f"preview_mapa_{geracao}"
    grupo = _grupo_preview(
        preview,
        cliques=cliques if modo != "Conferir" else None,
        mostrar_extremos=modo == "Conferir",
    )
    mapa_out = st_folium(
        _mapa_preview(preview, detalhado=True),
        key=chave_mapa,
        height=580,
        use_container_width=True,
        returned_objects=["last_clicked"],
        feature_group_to_add=grupo,
        zoom=zoom_forcar,
    )
    if mapa_out and modo != "Conferir":
        novo = clique_distinto(st.session_state.get("preview_click_visto"), mapa_out.get("last_clicked"))
        if novo:
            cru = novo
            novo = colar_clique_na_via(*cru)
            st.session_state["preview_click_visto"] = cru
            if cliques and clique_proximo(cliques[-1], novo):
                st.warning("Esse clique grudou no mesmo ponto. Clique mais longe, no outro extremo da rua.")
            else:
                cliques.append(novo)
                crus = list(st.session_state.get("preview_cliques_crus") or [])
                crus.append(cru)
                st.session_state["preview_cliques"] = cliques[:3]
                st.session_state["preview_cliques_crus"] = crus[:3]
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

st.page_link("app.py", label="← Consulta de elegibilidade")
marca()
st.title("🛠️ Cadastro de barreiras")
st.caption(
    "Cadastre ou edite ruas-barreira. Traçado **a pé** pelo eixo da via. "
    "No mapa: dê zoom, clique perto da rua (o ponto gruda no asfalto) e troque para satélite se precisar."
)
st.caption(f"Armazenamento: **{descricao_store(store)}**")

with st.container(border=True):
    _secao_formulario()

st.divider()

try:
    barreiras = store.listar()
except ErroExterno as e:
    st.error(str(e))
    st.stop()

cab_lista, busca_lista = st.columns([2, 2])
with cab_lista:
    st.subheader(f"{len(barreiras)} trechos cadastrados")
with busca_lista:
    filtro = st.text_input(
        "Filtrar lista",
        key="lista_busca_barreira",
        placeholder="Nome da via…",
        label_visibility="collapsed",
    )

visiveis = [
    b
    for b in sorted(barreiras, key=lambda x: x.rotulo)
    if not filtro.strip() or filtro.lower() in b.rotulo.lower()
]
if filtro.strip() and not visiveis:
    st.info("Nenhum trecho com esse nome.")

for barreira in visiveis:
    with st.expander(barreira.rotulo):
        meta1, meta2 = st.columns(2)
        with meta1:
            st.caption(f"ID: `{barreira.id}` · tipo: {barreira.tipo}")
            if barreira.numero_inicio or barreira.numero_fim:
                st.caption(
                    f"Faixa: nº {barreira.numero_inicio or '…'} – {barreira.numero_fim or '…'}"
                    f"{f' ({barreira.paridade})' if barreira.paridade else ''}"
                )
        with meta2:
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
