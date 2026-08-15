"""Testes de retry do GitHub store."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from core.barreiras_store import ConfigGitHub, GitHubBarreirasStore
from core.erros import ErroExterno
from testes.test_barreiras_store import barreira_exemplo


def _resposta_get(sha: str, features: list) -> MagicMock:
    conteudo = json.dumps({"type": "FeatureCollection", "features": features})
    import base64

    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "content": base64.b64encode(conteudo.encode()).decode(),
        "sha": sha,
    }
    return resp


def test_github_retry_em_conflito_409():
    from core.barreiras_geojson import barreira_para_feature

    store = GitHubBarreirasStore(ConfigGitHub(token="t", repo="o/r"))
    feature = barreira_para_feature(barreira_exemplo())
    get_resp = _resposta_get("sha1", [feature])

    put_conflito = MagicMock(status_code=409)
    put_ok = MagicMock(status_code=200)
    put_ok.json.return_value = {"content": {"sha": "sha2"}}

    with patch("core.barreiras_store.requests.get", return_value=get_resp):
        with patch("core.barreiras_store.requests.put", side_effect=[put_conflito, put_ok]) as put:
            with patch.object(store, "_ler_remoto", return_value=({"type": "FeatureCollection", "features": [feature]}, "sha_novo")):
                store._sha = "sha1"
                store.salvar_todas([barreira_exemplo()], mensagem="teste")
                assert put.call_count == 2


def test_github_falha_apos_duas_tentativas():
    store = GitHubBarreirasStore(ConfigGitHub(token="t", repo="o/r"))
    put_conflito = MagicMock(status_code=409)

    with patch("core.barreiras_store.requests.put", return_value=put_conflito):
        with patch.object(store, "_ler_remoto", return_value=({"type": "FeatureCollection", "features": []}, "sha")):
            store._sha = "sha1"
            with pytest.raises(ErroExterno, match="Outra edição"):
                store.salvar_todas([barreira_exemplo()], mensagem="teste")
