"""Testes de auth — credenciais desacopladas de st.secrets."""

from __future__ import annotations

import copy


def test_deepcopy_desacopla_credenciais():
    """Simula st.secrets read-only: cópia profunda deve ser mutável."""
    secrets_auth = {
        "cookie_name": "test",
        "credentials": {
            "usernames": {
                "admin": {
                    "email": "a@b.com",
                    "name": "Admin",
                    "password": "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lqrj2xjjA7lOjKO",
                }
            }
        },
    }
    config = copy.deepcopy(secrets_auth)
    config["credentials"]["usernames"]["admin"]["password"] = "mutado"
    assert secrets_auth["credentials"]["usernames"]["admin"]["password"].startswith("$2b$")
