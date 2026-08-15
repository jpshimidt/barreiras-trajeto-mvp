"""Testes de auth — conversão de secrets."""

from __future__ import annotations

from types import MappingProxyType

from core.auth_app import (
    _credenciais_mutaveis,
    _normalizar_senha,
    _normalizar_usuario,
    _to_plain_dict,
)


class _SecretLike:
    """Simula SecretDict: mapeamento sem ser dict, mutável internamente."""

    def __init__(self, data: dict):
        self._data = data

    def keys(self):
        return self._data.keys()

    def __getitem__(self, key):
        return self._data[key]


def test_to_plain_dict_secret_like():
    auth = _SecretLike(
        {
            "credentials": _SecretLike(
                {
                    "usernames": _SecretLike(
                        {
                            "admin": {
                                "email": "a@b.com",
                                "name": "Admin",
                                "password": "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lqrj2xjjA7lOjKO",
                            }
                        }
                    )
                }
            )
        }
    )
    plain = _to_plain_dict(auth)
    assert isinstance(plain, dict)
    assert plain["credentials"]["usernames"]["admin"]["email"] == "a@b.com"


def test_credenciais_mutaveis_permite_reassign_usernames(monkeypatch):
    secrets_auth = {
        "credentials": {
            "usernames": {
                "admin": {
                    "email": "a@b.com",
                    "name": "Admin",
                    "password": "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lqrj2xjjA7lOjKO",
                }
            }
        }
    }

    class FakeSecrets(dict):
        pass

    fake = FakeSecrets({"auth": secrets_auth})
    monkeypatch.setattr("core.auth_app.st.secrets", fake)

    credenciais = _credenciais_mutaveis()
    credenciais["usernames"] = {k.lower(): v for k, v in credenciais["usernames"].items()}
    assert "admin" in credenciais["usernames"]


def test_normalizar_senha_remove_espacos_e_lista():
    hash_exemplo = "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lqrj2xjjA7lOjKO"
    assert _normalizar_senha(f"{hash_exemplo} ") == hash_exemplo
    assert _normalizar_senha([hash_exemplo]) == hash_exemplo


def test_credenciais_mutaveis_normaliza_senha_com_espaco(monkeypatch):
    hash_exemplo = "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lqrj2xjjA7lOjKO"
    secrets_auth = {
        "credentials": {
            "usernames": {
                "Admin": {
                    "email": "a@b.com",
                    "name": "Admin",
                    "password": f"{hash_exemplo} ",
                }
            }
        }
    }

    class FakeSecrets(dict):
        pass

    fake = FakeSecrets({"auth": secrets_auth})
    monkeypatch.setattr("core.auth_app.st.secrets", fake)

    credenciais = _credenciais_mutaveis()
    assert credenciais["usernames"]["admin"]["password"] == hash_exemplo


def test_normalizar_usuario_preserva_email():
    usuario = _normalizar_usuario({"email": " a@b.com ", "password": " x "})
    assert usuario["email"] == "a@b.com"
    assert usuario["password"] == "x"


def test_to_plain_dict_mapping_proxy():
    original = MappingProxyType({"nested": {"b": 2}})
    copia = _to_plain_dict(dict(original))
    copia["nested"]["b"] = 3
    assert original["nested"]["b"] == 2
