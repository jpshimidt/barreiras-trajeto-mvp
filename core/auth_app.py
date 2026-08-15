"""Autenticação da interface Streamlit — protege chamadas às APIs pagas."""

from __future__ import annotations

import json
import os
from typing import Any

import streamlit as st
import streamlit_authenticator as stauth

from core.rate_limit import registrar_tentativa_login_falha
from core.seguranca import cookie_key_segura, senha_parece_hash
from core.sessao_privada import limpar_dados_pessoais_sessao


def _plain_dict(valor: Any) -> Any:
    """Converte SecretDict / AttrDict em dict/list Python mutável."""
    return json.loads(json.dumps(valor, default=str))


def _config_auth() -> dict[str, Any] | None:
    try:
        if "auth" not in st.secrets:
            return None
        return _plain_dict(dict(st.secrets["auth"]))
    except Exception:
        return None


def _credenciais_mutaveis(config: dict[str, Any]) -> dict[str, Any]:
    """Credenciais desacopladas de st.secrets para o streamlit-authenticator."""
    credenciais = _plain_dict(config.get("credentials") or {})
    usernames = credenciais.get("usernames") or {}
    return {
        "usernames": {
            str(usuario): _plain_dict(dados)
            for usuario, dados in dict(usernames).items()
        }
    }


def _validar_credenciais(credenciais: dict[str, Any]) -> None:
    """Recusa senhas em texto puro — sempre exige hash bcrypt."""
    usernames = (credenciais.get("usernames") or {}).values()
    for usuario in usernames:
        senha = str(usuario.get("password", ""))
        if senha and not senha_parece_hash(senha):
            st.error(
                "Senha em texto puro detectada nos Secrets. "
                "Gere um hash bcrypt e substitua o campo `password`."
            )
            st.stop()


def admin_usernames() -> set[str]:
    """Usuários autorizados a editar o cadastro de barreiras."""
    config = _config_auth() or {}
    brutos = config.get("admin_usernames") or []
    if isinstance(brutos, str):
        brutos = [brutos]
    return {str(u).strip() for u in brutos if str(u).strip()}


def usuario_e_admin() -> bool:
    usuario = st.session_state.get("username")
    return bool(usuario and usuario in admin_usernames())


def exigir_login() -> bool:
    """
    Exibe tela de login e devolve True se o usuário está autenticado.

    Credenciais em secrets.toml / Streamlit Cloud Secrets, seção [auth].
    """
    autenticado_antes = bool(st.session_state.get("authentication_status"))

    config = _config_auth()
    if not config:
        st.error(
            "Login não configurado. Defina a seção `[auth]` nos Secrets do Streamlit "
            "(veja `.streamlit/secrets.toml.example`)."
        )
        st.stop()
        return False

    credenciais = _credenciais_mutaveis(config)
    if not credenciais.get("usernames"):
        st.error("Seção `[auth.credentials]` ausente ou vazia nos Secrets.")
        st.stop()
        return False

    _validar_credenciais(credenciais)

    cookie = _plain_dict(config.get("cookie") or {})
    cookie_key = (
        str(cookie.get("key") or "")
        or str(config.get("cookie_key") or "")
        or os.environ.get("AUTH_COOKIE_KEY", "")
    ).strip()
    if not cookie_key_segura(cookie_key):
        st.error(
            "Chave de cookie (`cookie_key`) ausente ou insegura. "
            "Defina nos Secrets uma string aleatória com pelo menos 32 caracteres."
        )
        st.stop()
        return False

    authenticator = stauth.Authenticate(
        credenciais,
        str(cookie.get("name") or config.get("cookie_name") or "barreiras_auth"),
        cookie_key,
        float(cookie.get("expiry_days") or config.get("cookie_expiry_days") or 30),
        auto_hash=False,
    )

    authenticator.login(location="main", key="login_form")

    autenticado_agora = bool(st.session_state.get("authentication_status"))
    if autenticado_antes and not autenticado_agora:
        limpar_dados_pessoais_sessao()

    if autenticado_agora:
        with st.sidebar:
            authenticator.logout(location="sidebar", key="logout_btn")
            st.caption(f"Logado como **{st.session_state.get('name', '')}**")
        return True

    if st.session_state.get("authentication_status") is False:
        try:
            registrar_tentativa_login_falha()
        except Exception as e:
            st.error(str(e))
            st.stop()
        st.error("Usuário ou senha incorretos.")
    else:
        st.info("Faça login para usar a consulta de elegibilidade.")
    st.stop()
    return False


def exigir_admin() -> None:
    """Login + perfil administrador (cadastro de barreiras)."""
    exigir_login()
    if not usuario_e_admin():
        st.error("Acesso restrito a administradores do cadastro de barreiras.")
        st.stop()
