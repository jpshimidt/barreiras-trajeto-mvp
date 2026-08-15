"""CRUD do cadastro de barreiras — página administrativa."""

from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import date
from pathlib import Path

import streamlit as st

from core.auth_app import exigir_admin
from core.barreiras import Barreira, TIPOS_BARREIRA
from core.barreiras_cache import invalidar_cache_barreiras, store_barreiras
from core.barreiras_geojson import geometria_de_coords_json
from core.barreiras_store import descricao_store
from core.erros import ErroExterno

ARQUIVO_BARREIRAS = Path(__file__).resolve().parent.parent / "dados" / "barreiras.geojson"

st.set_page_config(page_title="Cadastro de barreiras", page_icon="🛠️", layout="wide")

exigir_admin()


def _slug(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", sem_acento.lower()).strip("-") or "barreira"


def _novo_id(nome: str) -> str:
    return f"{_slug(nome)}-{date.today().isoformat()}-{uuid.uuid4().hex[:6]}"


@st.cache_resource(show_spinner=False)
def _store():
    return store_barreiras(ARQUIVO_BARREIRAS)


def _formulario_barreira(barreira: Barreira | None, *, chave: str) -> Barreira | None:
    with st.form(f"form_{chave}", clear_on_submit=False):
        nome = st.text_input(
            "Nome da via",
            value=barreira.nome if barreira else "",
            key=f"{chave}_nome",
        )
        tipo = st.selectbox(
            "Tipo",
            TIPOS_BARREIRA,
            index=TIPOS_BARREIRA.index(barreira.tipo) if barreira and barreira.tipo in TIPOS_BARREIRA else 0,
            key=f"{chave}_tipo",
        )
        col1, col2, col3 = st.columns(3)
        with col1:
            numero_inicio = st.number_input(
                "Nº início (opcional)",
                min_value=0,
                value=(barreira.numero_inicio or 0) if barreira else 0,
                step=1,
                key=f"{chave}_num_inicio",
            )
        with col2:
            numero_fim = st.number_input(
                "Nº fim (opcional)",
                min_value=0,
                value=(barreira.numero_fim or 0) if barreira else 0,
                step=1,
                key=f"{chave}_num_fim",
            )
        with col3:
            paridade = st.selectbox(
                "Paridade",
                ["", "ambos", "par", "impar"],
                index=(
                    ["", "ambos", "par", "impar"].index(barreira.paridade or "")
                    if barreira and barreira.paridade in {"", "ambos", "par", "impar"}
                    else 0
                ),
                key=f"{chave}_paridade",
            )

        coords_padrao = ""
        if barreira:
            coords = list(barreira.geometria.coords)
            coords_padrao = str([[lon, lat] for lon, lat in coords])

        geometria_txt = st.text_area(
            "Geometria (LineString)",
            value=coords_padrao,
            height=120,
            help="Coordenadas `[[lon, lat], ...]` em EPSG:4326. Desenhe no geojson.io e cole aqui.",
            placeholder="[[-46.63, -23.51], [-46.62, -23.51]]",
            key=f"{chave}_geometria",
        )

        enviado = st.form_submit_button("Salvar", type="primary")
        if not enviado:
            return None
        if not nome.strip():
            st.error("Informe o nome da via.")
            return None
        if not geometria_txt.strip():
            st.error("Informe a geometria da barreira.")
            return None
        try:
            geometria = geometria_de_coords_json(geometria_txt.strip())
        except (ErroExterno, ValueError, TypeError) as e:
            st.error(str(e))
            return None

        return Barreira(
            id=barreira.id if barreira else _novo_id(nome),
            nome=nome.strip(),
            tipo=tipo,
            geometria=geometria,
            numero_inicio=int(numero_inicio) if numero_inicio > 0 else None,
            numero_fim=int(numero_fim) if numero_fim > 0 else None,
            paridade=paridade or None,
        )


store = _store()

st.title("🛠️ Cadastro de barreiras")
st.caption(
    "Crie, edite e remova trechos de barreira. "
    "As alterações persistem entre deploys quando o GitHub está configurado."
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
        if st.button("Remover", key=f"del_{barreira.id}", type="secondary"):
            try:
                store.remover(barreira.id, mensagem=f"Cadastro: remover {barreira.rotulo}")
                invalidar_cache_barreiras()
                st.success("Barreira removida.")
                st.rerun()
            except ErroExterno as e:
                st.error(str(e))
        editada = _formulario_barreira(barreira, chave=f"edit_{barreira.id}")
        if editada:
            try:
                store.atualizar(editada, mensagem=f"Cadastro: atualizar {editada.rotulo}")
                invalidar_cache_barreiras()
                st.success("Barreira atualizada.")
                st.rerun()
            except ErroExterno as e:
                st.error(str(e))

st.divider()
st.subheader("Nova barreira")
nova = _formulario_barreira(None, chave="nova")
if nova:
    try:
        store.criar(nova, mensagem=f"Cadastro: criar {nova.rotulo}")
        invalidar_cache_barreiras()
        st.success("Barreira criada.")
        st.rerun()
    except ErroExterno as e:
        st.error(str(e))
