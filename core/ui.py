"""Estilo da ferramenta — simples, alto contraste, sem visual de produto."""

from __future__ import annotations

import html

import streamlit as st

_CSS = """
<style>
:root {
  --ink: #111111;
  --ink-soft: #1a1a1a;
  --muted: #222222;
  --paper: #f4f1ea;
  --card: #ffffff;
  --line: #c8c4bb;
  --blue: #1d4ed8;
}

html, body, [class*="css"] {
  font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  color: var(--ink);
}

.stApp {
  background: #f4f1ea;
}

[data-testid="stHeader"] { background: #f4f1ea; }
[data-testid="stToolbar"] { right: 1rem; }

[data-testid="stAppViewContainer"] .main .block-container {
  padding-top: 1.1rem;
  padding-bottom: 3.5rem;
  max-width: 1100px;
}

[data-testid="stSidebar"] {
  background: #ece8df;
  border-right: 1px solid #c8c4bb;
}
[data-testid="stSidebar"] * { color: #111111 !important; }
[data-testid="stSidebar"] .stCaption,
[data-testid="stSidebar"] [data-testid="stCaption"],
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
  color: #1a1a1a !important;
}
[data-testid="stSidebar"] input,
[data-testid="stSidebar"] textarea {
  background: #ffffff !important;
  color: #111111 !important;
  border: 1px solid #8a867c !important;
}
[data-testid="stSidebar"] [data-testid="stMetric"] {
  background: #ffffff;
  border: 1px solid #c8c4bb;
  border-radius: 8px;
  padding: 0.55rem 0.7rem;
}
[data-testid="stSidebar"] [data-testid="stExpander"] {
  background: #ffffff;
  border-radius: 8px;
  border: 1px solid #c8c4bb;
}

/* Logout e demais botões da barra: fundo claro, texto preto. */
[data-testid="stSidebar"] .stButton > button,
[data-testid="stSidebar"] .stButton > button p,
[data-testid="stSidebar"] .stButton > button span,
[data-testid="stSidebar"] .stButton > button * {
  background: #ffffff !important;
  color: #111111 !important;
  border: 1px solid #111111 !important;
  font-weight: 700 !important;
}

h1, h2, h3 {
  color: #111111 !important;
  letter-spacing: 0 !important;
}

p, label, li, .stMarkdown, .stMarkdown p, .stText,
[data-testid="stWidgetLabel"] p,
[data-testid="stCaption"],
[data-testid="stCaptionContainer"],
[data-testid="stCaptionContainer"] p,
small {
  color: #111111 !important;
}

.stButton > button {
  border-radius: 8px !important;
  font-weight: 700 !important;
  min-height: 2.7rem;
}
.stButton > button[kind="primary"],
.stButton > button[kind="primary"]:disabled,
[data-testid="stBaseButton-primary"] {
  background: #1d4ed8 !important;
  border: 1px solid #153eab !important;
  box-shadow: none !important;
}
.stButton > button[kind="primary"] p,
.stButton > button[kind="primary"] span,
.stButton > button[kind="primary"] div,
.stButton > button[kind="primary"] *,
[data-testid="stBaseButton-primary"],
[data-testid="stBaseButton-primary"] p,
[data-testid="stBaseButton-primary"] span,
[data-testid="stBaseButton-primary"] * {
  color: #ffffff !important;
  font-weight: 700 !important;
}
.stButton > button[kind="secondary"],
.stButton > button:not([kind="primary"]) {
  background: #ffffff !important;
  border: 1px solid #111111 !important;
}
.stButton > button[kind="secondary"] *,
.stButton > button:not([kind="primary"]) * {
  color: #111111 !important;
}

div[data-testid="stVerticalBlockBorderWrapper"] {
  background: #ffffff;
  border: 1px solid #c8c4bb !important;
  border-radius: 10px !important;
  box-shadow: none;
}

[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stSelectbox"] > div {
  border-radius: 6px !important;
  color: #111111 !important;
}

[data-testid="stAlert"] {
  border-radius: 8px !important;
}
[data-testid="stAlert"]:has(h2) {
  position: absolute !important;
  width: 1px !important;
  height: 1px !important;
  overflow: hidden !important;
  clip: rect(0, 0, 0, 0) !important;
}

footer { visibility: hidden; }

.hero-kicker {
  margin: 0 0 0.35rem 0;
  color: #111111;
  font-size: 0.92rem;
  font-weight: 700;
}
.hero-lead {
  max-width: 46rem;
  color: #111111;
  font-size: 1.02rem;
  line-height: 1.5;
  margin: 0 0 1rem 0;
}

.passos {
  margin: 0 0 1.1rem 0;
  padding: 0.75rem 0.9rem;
  background: #ffffff;
  border: 1px solid #c8c4bb;
  border-radius: 8px;
}
.passo { margin: 0.2rem 0; color: #111111; font-size: 0.95rem; line-height: 1.45; }
.passo-n { font-weight: 700; }

.veredito {
  padding: 1rem 1.1rem;
  border-radius: 8px;
  color: #ffffff;
  margin: 0 0 0.7rem 0;
}
.veredito-sim { background: #166534; }
.veredito-nao { background: #9f1239; }
.veredito-k {
  font-size: 0.8rem;
  font-weight: 700;
  color: #ffffff;
  margin-bottom: 0.2rem;
}
.veredito-t {
  font-size: 1.7rem;
  line-height: 1.15;
  font-weight: 800;
  color: #ffffff;
}
.veredito-m { font-size: 1.02rem; line-height: 1.45; color: #ffffff; margin-top: 0.35rem; }

.chips { display: flex; flex-wrap: wrap; gap: 0.7rem; margin: 0.35rem 0 0.55rem; }
.chip {
  display: inline-flex; align-items: center; gap: 0.35rem;
  font-size: 0.92rem;
  color: #111111;
  font-weight: 600;
}
.chip b { width: 10px; height: 10px; border-radius: 99px; display: inline-block; }
.chip-azul b { background: #1f6feb; }
.chip-vermelho b { background: #b91c1c; }
.chip-casa b { background: #1d4ed8; }
.chip-escola b { background: #15803d; }

.side-brand { margin: 0.1rem 0 0.8rem; }
.side-name { font-weight: 800; font-size: 1.05rem; color: #111111; }
.side-sub { font-size: 0.9rem; color: #111111 !important; font-weight: 600; }

.login-rodape {
  margin-top: 1rem;
  color: #111111;
  font-size: 0.92rem;
}
</style>
"""


def aplicar_estilo() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def marca(texto: str = "São Paulo · transporte escolar") -> None:
    st.markdown(
        f'<div class="hero-kicker">{html.escape(texto)}</div>',
        unsafe_allow_html=True,
    )


def lead(texto: str) -> None:
    st.markdown(f'<p class="hero-lead">{html.escape(texto)}</p>', unsafe_allow_html=True)


def passos_consulta() -> None:
    st.markdown(
        """
<div class="passos">
  <div class="passo"><span class="passo-n">1.</span> Informe casa e escola em São Paulo.</div>
  <div class="passo"><span class="passo-n">2.</span> O app calcula o menor caminho a pé — nunca GPS de carro.</div>
  <div class="passo"><span class="passo-n">3.</span> Se a rota encosta numa rua-barreira, há direito.</div>
</div>
""",
        unsafe_allow_html=True,
    )


def sidebar_marca() -> None:
    st.markdown(
        """
<div class="side-brand">
  <div class="side-name">Barreiras</div>
  <div class="side-sub">Transporte escolar</div>
</div>
""",
        unsafe_allow_html=True,
    )


def veredito(resultado) -> None:
    """Cartão de decisão. Mantém st.success/error para os testes da interface."""
    if resultado.tem_direito:
        st.success("## ✅ COM DIREITO")
        classe = "veredito veredito-sim"
        titulo = "Com direito"
    else:
        st.error("## ❌ SEM DIREITO")
        classe = "veredito veredito-nao"
        titulo = "Sem direito"
    motivo = html.escape(resultado.motivo)
    st.markdown(
        f"""
<div class="{classe}">
  <div class="veredito-k">Decisão</div>
  <div class="veredito-t">{titulo}</div>
  <div class="veredito-m">{motivo}</div>
</div>
""",
        unsafe_allow_html=True,
    )


def chips_mapa() -> None:
    st.markdown(
        """
<div class="chips">
  <span class="chip chip-azul"><b></b>Rota a pé</span>
  <span class="chip chip-vermelho"><b></b>Barreira tocada</span>
  <span class="chip chip-casa"><b></b>A · casa</span>
  <span class="chip chip-escola"><b></b>B · escola</span>
</div>
""",
        unsafe_allow_html=True,
    )
