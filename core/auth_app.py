"""Autenticação da interface Streamlit — protege chamadas às APIs pagas."""

from __future__ import annotations

import os
from typing import Any

import streamlit as st
import streamlit_authenticator as stauth

from core.rate_limit import registrar_tentativa_login_falha
from core.seguranca import cookie_key_segura, senha_parece_hash
from core.sessao_privada import limpar_dados_pessoais_sessao


def _to_plain_dict(valor: Any) -> Any:
    """
    Converte SecretDict / AttrDict do Streamlit em dict Python mutável.

    Evita json.dumps — objetos internos dos secrets viram string e quebram .get().
    """
    if valor is None or isinstance(valor, (str, int, float, bool)):
        return valor
    if isinstance(valor, dict):
        return {str(k): _to_plain_dict(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_to_plain_dict(v) for v in valor]
    if hasattr(valor, "keys"):
        try:
            return {str(k): _to_plain_dict(valor[k]) for k in valor.keys()}
        except Exception:
            pass
    return valor


def _config_auth() -> dict[str, Any] | None:
    try:
        if "auth" not in st.secrets:
            return None
        return _to_plain_dict(st.secrets["auth"])
    except Exception:
        return None


def _credenciais_mutaveis() -> dict[str, Any]:
    """Credenciais desacopladas de st.secrets para o streamlit-authenticator."""
    try:
        credenciais = _to_plain_dict(st.secrets["auth"]["credentials"])
    except Exception:
        return {"usernames": {}}

    if not isinstance(credenciais, dict):
        return {"usernames": {}}

    usernames = credenciais.get("usernames") or {}
    if not isinstance(usernames, dict):
        return {"usernames": {}}

    return {
        "usernames": {
            str(usuario): _to_plain_dict(dados)
            for usuario, dados in usernames.items()
        }
    }


def _validar_credenciais(credenciais: dict[str, Any]) -> None:
    """Recusa senhas em texto puro — sempre exige hash bcrypt."""
    usernames = (credenciais.get("usernames") or {}).values()
    for usuario in usernames:
        if not isinstance(usuario, dict):
            continue
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

    credenciais = _credenciais_mutaveis()
    if not credenciais.get("usernames"):
        st.error("Seção `[auth.credentials]` ausente ou vazia nos Secrets.")
        st.stop()
        return False

    _validar_credenciais(credenciais)

    cookie = config.get("cookie") or {}
    if not isinstance(cookie, dict):
        cookie = {}
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
