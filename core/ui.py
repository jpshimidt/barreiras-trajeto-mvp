"""Identidade visual — cores e cartões de antes, com contraste ajustado."""

from __future__ import annotations

import html

import streamlit as st

_CSS = """
<style>
:root {
  --ink: #111111;
  --ink-soft: #1f2430;
  --muted: #2c3340;
  --paper: #f3efe6;
  --card: #fffcf7;
  --line: rgba(16, 20, 28, 0.10);
  --blue: #2453d6;
  --blue-deep: #1636a0;
  --teal: #0f766e;
  --rose: #be123c;
  --shadow: 0 18px 50px -28px rgba(16, 20, 28, 0.45);
}

html, body, [class*="css"] {
  font-family: "SF Pro Display", "Segoe UI", "Helvetica Neue", sans-serif;
}

.stApp {
  background:
    radial-gradient(900px 420px at 100% -8%, rgba(36, 83, 214, 0.16), transparent 50%),
    radial-gradient(800px 380px at -10% 0%, rgba(15, 118, 110, 0.10), transparent 46%),
    linear-gradient(180deg, #f7f3ea 0%, #efe8d8 100%);
}

.stApp:before {
  content: "";
  position: fixed;
  inset: 0 0 auto 0;
  height: 4px;
  z-index: 100;
  background: linear-gradient(90deg, #1636a0, #2453d6 40%, #0f766e 78%, #e11d48);
}

[data-testid="stHeader"] { background: transparent; }
[data-testid="stToolbar"] { right: 1rem; }

[data-testid="stAppViewContainer"] .main .block-container {
  padding-top: 1.15rem;
  padding-bottom: 4rem;
  max-width: 1120px;
}

[data-testid="stSidebar"] {
  background:
    radial-gradient(400px 240px at 20% 0%, rgba(36, 83, 214, 0.35), transparent 60%),
    linear-gradient(180deg, #121826 0%, #0c111b 100%);
  border-right: 0;
  color: #e8edf7;
}
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] li,
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3,
[data-testid="stSidebar"] .stMarkdown,
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
[data-testid="stSidebar"] [data-testid="stMetricValue"],
[data-testid="stSidebar"] [data-testid="stMetricLabel"],
[data-testid="stSidebar"] [data-testid="stMetricDelta"] {
  color: #e8edf7 !important;
}
[data-testid="stSidebar"] .stCaption,
[data-testid="stSidebar"] [data-testid="stCaption"],
[data-testid="stSidebar"] [data-testid="stCaptionContainer"],
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {
  color: #d4dbe8 !important;
}
[data-testid="stSidebar"] a { color: #c9d7ff !important; }
[data-testid="stSidebar"] input,
[data-testid="stSidebar"] textarea {
  background: rgba(255,255,255,0.08) !important;
  color: #f8fafc !important;
  border: 1px solid rgba(255,255,255,0.18) !important;
}
[data-testid="stSidebar"] [data-testid="stMetric"] {
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 16px;
  padding: 0.7rem 0.85rem;
}
[data-testid="stSidebar"] [data-testid="stExpander"] {
  background: rgba(255,255,255,0.04);
  border-radius: 14px;
  border: 1px solid rgba(255,255,255,0.08);
}

/* Logout: botão claro com texto preto — não herda o branco da sidebar. */
[data-testid="stSidebar"] .stButton > button,
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"],
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] {
  background: #fff8ee !important;
  color: #111111 !important;
  border: 2px solid #111111 !important;
  font-weight: 800 !important;
  min-height: 2.55rem;
  box-shadow: none !important;
}
[data-testid="stSidebar"] .stButton > button p,
[data-testid="stSidebar"] .stButton > button span,
[data-testid="stSidebar"] .stButton > button *,
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] *,
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] * {
  color: #111111 !important;
  font-weight: 800 !important;
}

h1 {
  font-size: 2.55rem !important;
  line-height: 1.05 !important;
  letter-spacing: -0.045em !important;
  font-weight: 700 !important;
  color: var(--ink) !important;
  margin-bottom: 0.35rem !important;
}
h2, h3 {
  letter-spacing: -0.03em !important;
  color: var(--ink) !important;
}

p, label, li, .stMarkdown, .stMarkdown p, .stText,
[data-testid="stWidgetLabel"] p,
[data-testid="stCaption"],
[data-testid="stCaptionContainer"],
[data-testid="stCaptionContainer"] p,
small {
  color: var(--ink-soft) !important;
}

.stButton > button {
  border-radius: 14px !important;
  font-weight: 700 !important;
  letter-spacing: -0.01em;
  transition: transform .15s ease, box-shadow .15s ease;
}
.stButton > button[kind="primary"],
.stButton > button[kind="primary"]:disabled,
[data-testid="stBaseButton-primary"] {
  min-height: 3rem;
  background: linear-gradient(180deg, #3b6bff 0%, #2453d6 100%) !important;
  border: 0 !important;
  box-shadow: 0 10px 24px -12px rgba(36, 83, 214, 0.8);
  color: #ffffff !important;
}
.stButton > button[kind="primary"] p,
.stButton > button[kind="primary"] span,
.stButton > button[kind="primary"] div,
.stButton > button[kind="primary"] *,
[data-testid="stBaseButton-primary"] p,
[data-testid="stBaseButton-primary"] span,
[data-testid="stBaseButton-primary"] * {
  color: #ffffff !important;
  font-weight: 700 !important;
}
.stButton > button[kind="primary"]:hover {
  transform: translateY(-1px);
  box-shadow: 0 16px 30px -12px rgba(36, 83, 214, 0.9);
}

div[data-testid="stVerticalBlockBorderWrapper"] {
  background: var(--card);
  border: 1px solid var(--line) !important;
  border-radius: 22px !important;
  box-shadow: var(--shadow);
  padding: 0.15rem;
}

[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stSelectbox"] > div {
  border-radius: 12px !important;
  min-height: 2.6rem;
  color: var(--ink) !important;
}

[data-testid="stAlert"] {
  border: 0 !important;
  border-radius: 18px !important;
  box-shadow: var(--shadow);
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
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  margin: 0 0 0.7rem 0;
  padding: 0.28rem 0.7rem;
  border-radius: 999px;
  background: rgba(36, 83, 214, 0.08);
  color: var(--blue-deep);
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}
.hero-kicker i {
  width: 7px; height: 7px; border-radius: 99px;
  background: var(--blue);
  display: inline-block;
}
.hero-lead {
  max-width: 46rem;
  color: var(--ink-soft);
  font-size: 1.05rem;
  line-height: 1.55;
  margin: 0 0 1.3rem 0;
}

.passos {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.75rem;
  margin: 0 0 1.4rem 0;
}
.passo {
  position: relative;
  padding: 1rem 1rem 1rem 1.05rem;
  border-radius: 18px;
  background: var(--card);
  border: 1px solid var(--line);
  box-shadow: var(--shadow);
  overflow: hidden;
}
.passo:before {
  content: "";
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 4px;
  background: linear-gradient(180deg, var(--blue), var(--teal));
}
.passo-n {
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--blue);
  margin-bottom: 0.25rem;
}
.passo-t { font-weight: 700; color: var(--ink); letter-spacing: -0.02em; }
.passo-d { margin-top: 0.25rem; color: var(--muted); font-size: 0.88rem; line-height: 1.4; }

.veredito {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  padding: 1.35rem 1.4rem 1.25rem;
  border-radius: 22px;
  color: #fff;
  box-shadow: var(--shadow);
  margin: 0 0 0.8rem 0;
}
.veredito-sim {
  background:
    radial-gradient(500px 180px at 100% 0%, rgba(255,255,255,0.18), transparent 50%),
    linear-gradient(135deg, #0f766e 0%, #115e59 55%, #134e4a 100%);
}
.veredito-nao {
  background:
    radial-gradient(500px 180px at 100% 0%, rgba(255,255,255,0.16), transparent 50%),
    linear-gradient(135deg, #be123c 0%, #9f1239 55%, #881337 100%);
}
.veredito-k {
  font-size: 0.72rem;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  opacity: 0.9;
  font-weight: 700;
  color: #fff;
}
.veredito-t {
  font-size: 2.1rem;
  line-height: 1;
  letter-spacing: -0.045em;
  font-weight: 750;
  color: #fff;
}
.veredito-m { font-size: 1.02rem; line-height: 1.45; color: #fff; }

.chips { display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 0.4rem 0 0.2rem; }
.chip {
  display: inline-flex; align-items: center; gap: 0.35rem;
  padding: 0.28rem 0.65rem;
  border-radius: 999px;
  background: rgba(16,20,28,0.05);
  border: 1px solid var(--line);
  font-size: 0.8rem;
  color: var(--ink-soft);
  font-weight: 600;
}
.chip b { width: 8px; height: 8px; border-radius: 99px; display: inline-block; }
.chip-azul b { background: #1f6feb; }
.chip-vermelho b { background: #d1242f; }
.chip-casa b { background: #2563eb; }
.chip-escola b { background: #16a34a; }

.side-brand {
  display: flex; align-items: center; gap: 0.75rem;
  margin: 0.2rem 0 1.1rem;
}
.side-mark {
  width: 40px; height: 40px; border-radius: 12px;
  display: grid; place-items: center;
  background: linear-gradient(180deg, #3b6bff, #1636a0);
  font-weight: 800; letter-spacing: -0.04em;
  color: #fff;
  box-shadow: 0 10px 20px -12px rgba(36,83,214,.9);
}
.side-name { font-weight: 750; letter-spacing: -0.03em; font-size: 1.05rem; color: #e8edf7; }
.side-sub { font-size: 0.78rem; color: #d4dbe8 !important; }

.login-rodape {
  margin-top: 1.1rem;
  color: var(--ink-soft);
  font-size: 0.9rem;
}

/* Depois das regras globais de tinta escura: a sidebar continua clara. */
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] li,
[data-testid="stSidebar"] .stMarkdown,
[data-testid="stSidebar"] .stMarkdown p,
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
[data-testid="stSidebar"] [data-testid="stCaption"],
[data-testid="stSidebar"] [data-testid="stCaptionContainer"],
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p,
[data-testid="stSidebar"] small {
  color: #e8edf7 !important;
}
[data-testid="stSidebar"] .stCaption,
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {
  color: #d4dbe8 !important;
}
[data-testid="stSidebar"] .stButton > button,
[data-testid="stSidebar"] .stButton > button *,
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"],
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] *,
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"],
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] * {
  color: #111111 !important;
}
</style>
"""


def aplicar_estilo() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def marca(texto: str = "São Paulo · transporte escolar") -> None:
    st.markdown(
        f'<div class="hero-kicker"><i></i>{html.escape(texto)}</div>',
        unsafe_allow_html=True,
    )


def lead(texto: str) -> None:
    st.markdown(f'<p class="hero-lead">{html.escape(texto)}</p>', unsafe_allow_html=True)


def passos_consulta() -> None:
    st.markdown(
        """
<div class="passos">
  <div class="passo">
    <div class="passo-n">Passo 01</div>
    <div class="passo-t">Endereços</div>
    <div class="passo-d">Casa e escola em São Paulo, como no Maps.</div>
  </div>
  <div class="passo">
    <div class="passo-n">Passo 02</div>
    <div class="passo-t">Caminho a pé</div>
    <div class="passo-d">O menor trajeto a pé — nunca GPS de carro.</div>
  </div>
  <div class="passo">
    <div class="passo-n">Passo 03</div>
    <div class="passo-t">Barreira</div>
    <div class="passo-d">Se a rota encosta numa rua-barreira, há direito.</div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def sidebar_marca() -> None:
    st.markdown(
        """
<div class="side-brand">
  <div class="side-mark">SP</div>
  <div>
    <div class="side-name">Barreiras</div>
    <div class="side-sub">Transporte escolar</div>
  </div>
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
