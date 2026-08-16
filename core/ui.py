"""Visual compartilhado das páginas Streamlit — só apresentação, sem regra."""

from __future__ import annotations

import streamlit as st

_CSS = """
<style>
html, body, [class*="css"] {
  font-family: "Source Sans 3", "Source Sans Pro", "Segoe UI", sans-serif;
}

.stApp {
  background:
    radial-gradient(1200px 500px at 10% -10%, #dbe7ff 0%, transparent 55%),
    #f4f1ea;
}

[data-testid="stHeader"] {
  background: transparent;
}

[data-testid="stToolbar"] {
  right: 1rem;
}

[data-testid="stSidebar"] {
  background: #faf8f4;
  border-right: 1px solid #e8e2d6;
}

[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
  letter-spacing: -0.02em;
}

[data-testid="stAppViewContainer"] .main .block-container {
  padding-top: 1.6rem;
  padding-bottom: 3rem;
  max-width: 1180px;
}

h1 {
  letter-spacing: -0.03em;
  font-weight: 700 !important;
}

h2, h3 {
  letter-spacing: -0.02em;
}

.marca {
  margin: 0 0 0.2rem 0;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #1d4ed8;
}

.passo {
  min-height: 5.2rem;
}

.stButton > button {
  border-radius: 10px;
  font-weight: 600;
}

.stButton > button[kind="primary"] {
  min-height: 2.7rem;
  box-shadow: 0 1px 0 rgba(15, 23, 42, 0.08);
}

[data-testid="stMetric"] {
  background: #fff;
  border: 1px solid #e8e2d6;
  border-radius: 12px;
  padding: 0.55rem 0.75rem;
}

[data-testid="stAlert"] {
  border-radius: 12px;
}

div[data-testid="stVerticalBlockBorderWrapper"] {
  background: #fff;
  border-color: #e8e2d6 !important;
  border-radius: 16px !important;
  box-shadow: 0 1px 2px rgba(28, 25, 23, 0.04);
}

footer {
  visibility: hidden;
}

.login-rodape {
  margin-top: 1.2rem;
  color: #78716c;
  font-size: 0.85rem;
}
</style>
"""


def aplicar_estilo() -> None:
    """Aplica o CSS em todo rerun — o Streamlit descarta o anterior."""
    st.markdown(_CSS, unsafe_allow_html=True)


def marca(texto: str = "São Paulo · transporte escolar") -> None:
    st.markdown(f'<p class="marca">{texto}</p>', unsafe_allow_html=True)
