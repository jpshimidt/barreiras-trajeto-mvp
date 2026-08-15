"""Autenticação da interface Streamlit — protege chamadas às APIs pagas."""

from __future__ import annotations

import os
from typing import Any

import streamlit as st
import streamlit_authenticator as stauth

_COOKIE_KEYS_PADRAO = frozenset(
    {
        "troque-esta-chave-secreta",
        "gere-uma-string-aleatoria-longa-e-secreta",
    }
)


def auth_desabilitado() -> bool:
    """Permite desenvolvimento local sem secrets de login (`AUTH_DISABLED=1`)."""
    valor = os.environ.get("AUTH_DISABLED", "").strip().lower()
    return valor in {"1", "true", "yes", "on"}


def _config_auth() -> dict[str, Any] | None:
    try:
        if "auth" in st.secrets:
            return dict(st.secrets["auth"])
    except Exception:
        pass
    return None


def exigir_login() -> bool:
    """
    Exibe tela de login e devolve True se o usuário está autenticado.

    Credenciais em secrets.toml / Streamlit Cloud Secrets, seção [auth].
    """
    if auth_desabilitado():
        return True

    config = _config_auth()
    if not config:
        st.error(
            "Login não configurado. Defina a seção `[auth]` nos Secrets do Streamlit "
            "(veja `.streamlit/secrets.toml.example`)."
        )
        st.stop()
        return False

    credenciais = config.get("credentials")
    if not credenciais:
        st.error("Seção `[auth.credentials]` ausente nos Secrets.")
        st.stop()
        return False

    cookie = config.get("cookie") or {}
    cookie_key = (
        cookie.get("key")
        or config.get("cookie_key")
        or os.environ.get("AUTH_COOKIE_KEY", "troque-esta-chave-secreta")
    )
    if cookie_key in _COOKIE_KEYS_PADRAO:
        st.sidebar.warning(
            "Configure `cookie_key` nos Secrets com uma string aleatória longa — "
            "a chave padrão não é segura em produção."
        )

    authenticator = stauth.Authenticate(
        credenciais,
        cookie.get("name") or config.get("cookie_name", "barreiras_auth"),
        cookie_key,
        float(cookie.get("expiry_days") or config.get("cookie_expiry_days", 30)),
    )

    authenticator.login(location="main", key="login_form")

    if st.session_state.get("authentication_status"):
        with st.sidebar:
            authenticator.logout(location="sidebar", key="logout_btn")
            st.caption(f"Logado como **{st.session_state.get('name', '')}**")
        return True

    if st.session_state.get("authentication_status") is False:
        st.error("Usuário ou senha incorretos.")
    else:
        st.info("Faça login para usar a consulta de elegibilidade.")
    st.stop()
    return False
