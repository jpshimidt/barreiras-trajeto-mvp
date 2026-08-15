"""Testes de auth — credenciais desacopladas de st.secrets."""

from __future__ import annotations

from types import MappingProxyType

from core.auth_app import _credenciais_mutaveis, _plain_dict


class _ReadOnlyUsernames(dict):
    def __setitem__(self, key, value):
        raise TypeError("read-only")


def test_credenciais_mutaveis_permite_reassign_usernames():
    config = {
        "credentials": {
            "usernames": _ReadOnlyUsernames(
                {
                    "admin": {
                        "email": "a@b.com",
                        "name": "Admin",
                        "password": "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lqrj2xjjA7lOjKO",
                    }
                }
            )
        }
    }
    credenciais = _credenciais_mutaveis(config)
    credenciais["usernames"] = {k.lower(): v for k, v in credenciais["usernames"].items()}
    assert "admin" in credenciais["usernames"]


def test_plain_dict_desacopla_mapping_proxy():
    original = MappingProxyType({"a": 1, "nested": {"b": 2}})
    copia = _plain_dict(dict(original))
    copia["nested"]["b"] = 3
    assert original["nested"]["b"] == 2
