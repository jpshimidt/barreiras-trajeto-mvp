"""Verificações de segurança em tempo de execução."""

from __future__ import annotations

import os
import re

_CHAVES_COOKIE_INSEGURAS = frozenset(
    {
        "troque-esta-chave-secreta",
        "gere-uma-string-aleatoria-longa-e-secreta",
        "change-me",
        "secret",
    }
)
_HASH_BCRYPT = re.compile(r"^\$2[aby]\$\d{2}\$.{53}$")


def cookie_key_segura(chave: str) -> bool:
    chave = chave.strip()
    if len(chave) < 32:
        return False
    return chave.lower() not in _CHAVES_COOKIE_INSEGURAS


def senha_parece_hash(valor: str) -> bool:
    return bool(_HASH_BCRYPT.match(valor.strip()))


def em_ambiente_streamlit_cloud() -> bool:
    """Heurística: Streamlit Cloud define variáveis de ambiente conhecidas."""
    return bool(
        os.environ.get("STREAMLIT_SHARING_MODE")
        or os.environ.get("STREAMLIT_RUNTIME_ENV") == "cloud"
        or os.environ.get("IS_STREAMLIT_CLOUD")
    )
