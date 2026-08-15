"""Testes de autenticação (sem UI)."""

from __future__ import annotations

import core.auth_app as auth


def test_auth_desabilitado_por_env(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "1")
    assert auth.auth_desabilitado() is True

    monkeypatch.setenv("AUTH_DISABLED", "true")
    assert auth.auth_desabilitado() is True

    monkeypatch.setenv("AUTH_DISABLED", "0")
    assert auth.auth_desabilitado() is False
