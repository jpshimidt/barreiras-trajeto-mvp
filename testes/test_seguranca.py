"""Testes do módulo de segurança."""

from __future__ import annotations

from core.seguranca import cookie_key_segura, senha_parece_hash


def test_cookie_key_curta_e_insegura():
    assert cookie_key_segura("abc") is False


def test_cookie_key_padrao_e_insegura():
    assert cookie_key_segura("troque-esta-chave-secreta") is False


def test_cookie_key_longa_e_aceita():
    assert cookie_key_segura("x" * 40) is True


def test_senha_hash_bcrypt_reconhecida():
    hash_exemplo = "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lqrj2xjjA7lOjKO"
    assert senha_parece_hash(hash_exemplo) is True


def test_senha_texto_puro_nao_e_hash():
    assert senha_parece_hash("minha-senha") is False
