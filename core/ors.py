"""Acesso ao OpenRouteService: chave e tradução de erro HTTP."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

import requests

from core.erros import ErroExterno

TIMEOUT_S = 30

RAIZ = Path(__file__).resolve().parent.parent
SECRETS = RAIZ / ".streamlit" / "secrets.toml"


def ler_api_key() -> str:
    """
    Variável de ambiente primeiro, `.streamlit/secrets.toml` depois.

    O arquivo está no `.gitignore` desde o primeiro commit — a chave nunca entra
    no repositório, e no Streamlit Cloud ela vem do painel Settings → Secrets.
    """
    chave = os.environ.get("ORS_API_KEY")
    if chave and chave.strip():
        return chave.strip()

    if SECRETS.exists():
        with open(SECRETS, "rb") as f:
            dados = tomllib.load(f)
        chave = dados.get("ORS_API_KEY") or (dados.get("ors") or {}).get("api_key")
        if chave and str(chave).strip():
            return str(chave).strip()

    raise ErroExterno(
        "Chave do OpenRouteService não encontrada.\n"
        "  export ORS_API_KEY='sua-chave'   (crie em openrouteservice.org)\n"
        "  ou rode com --offline para validar só a geometria, sem chamar a API."
    )


def erro_http(resp: requests.Response, etapa: str) -> ErroExterno:
    if resp.status_code == 429:
        return ErroExterno(
            f"{etapa}: cota do OpenRouteService estourada (HTTP 429). Tente de novo mais tarde."
        )
    if resp.status_code in (401, 403):
        return ErroExterno(
            f"{etapa}: chave do OpenRouteService inválida ou sem permissão (HTTP {resp.status_code})."
        )
    return ErroExterno(
        f"{etapa}: OpenRouteService respondeu HTTP {resp.status_code} — {resp.text[:200]}"
    )
