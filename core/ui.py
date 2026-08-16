"""Identidade visual do produto — só apresentação, sem regra."""

from __future__ import annotations

import html

import streamlit as st

_CSS = """
<style>
:root {
  --ink: #10141c;
  --ink-soft: #3d4553;
  --muted: #6b7280;
  --paper: #f3efe6;
  --card: #fffcf7;
  --line: rgba(16, 20, 28, 0.08);
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
}
[data-testid="stSidebar"] * { color: #e8edf7 !important; }
[data-testid="stSidebar"] .stCaption,
[data-testid="stSidebar"] [data-testid="stCaption"] { color: #9aa6bd !important; }
[data-testid="stSidebar"] input,
[data-testid="stSidebar"] textarea {
  background: rgba(255,255,255,0.06) !important;
  color: #f8fafc !important;
  border: 1px solid rgba(255,255,255,0.12) !important;
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

.stButton > button {
  border-radius: 14px !important;
  font-weight: 650 !important;
  letter-spacing: -0.01em;
  transition: transform .15s ease, box-shadow .15s ease;
}
.stButton > button[kind="primary"] {
  min-height: 3rem;
  background: linear-gradient(180deg, #3b6bff 0%, #2453d6 100%) !important;
  border: 0 !important;
  box-shadow: 0 10px 24px -12px rgba(36, 83, 214, 0.8);
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
  opacity: 0.8;
  font-weight: 700;
}
.veredito-t {
  font-size: 2.1rem;
  line-height: 1;
  letter-spacing: -0.045em;
  font-weight: 750;
}
.veredito-m { font-size: 1.02rem; line-height: 1.45; opacity: 0.95; }

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
  box-shadow: 0 10px 20px -12px rgba(36,83,214,.9);
}
.side-name { font-weight: 750; letter-spacing: -0.03em; font-size: 1.05rem; }
.side-sub { font-size: 0.78rem; color: #9aa6bd !important; }

.login-split {
  display: grid;
  grid-template-columns: 1fr;
  gap: 0;
}
.login-art {
  display: none;
}
@media (min-width: 880px) {
  .login-art { display: block; }
}

.login-art {
  position: relative;
  min-height: 22rem;
  border-radius: 28px;
  overflow: hidden;
  background:
    radial-gradient(420px 220px at 80% 10%, rgba(36,83,214,.45), transparent 55%),
    radial-gradient(340px 200px at 10% 90%, rgba(15,118,110,.35), transparent 50%),
    linear-gradient(160deg, #121826 0%, #0b1020 100%);
  color: #eef3ff;
  padding: 2rem 1.8rem;
  box-shadow: var(--shadow);
}
.login-art:after {
  content: "";
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255,255,255,0.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.05) 1px, transparent 1px);
  background-size: 42px 42px;
  mask-image: linear-gradient(180deg, rgba(0,0,0,.55), transparent 80%);
  pointer-events: none;
}
.login-art h2 {
  position: relative;
  z-index: 1;
  color: #fff !important;
  font-size: 2rem;
  letter-spacing: -0.04em;
  margin: 2.2rem 0 0.6rem;
}
.login-art p {
  position: relative;
  z-index: 1;
  color: #c5d0e8;
  line-height: 1.5;
  max-width: 22rem;
}
.login-rodape {
  margin-top: 1.1rem;
  color: var(--muted);
  font-size: 0.84rem;
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


def painel_login() -> None:
    st.markdown(
        """
<div class="login-art">
  <div class="hero-kicker" style="background:rgba(255,255,255,.08);color:#d7e2ff"><i></i>Município de São Paulo</div>
  <h2>O caminho a pé decide o direito.</h2>
  <p>Consulta de elegibilidade ao transporte escolar. Sem banco de dados, sem histórico — só esta sessão.</p>
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
