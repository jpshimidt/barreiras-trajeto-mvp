"""Persistência do cadastro de barreiras — arquivo local ou GitHub."""

from __future__ import annotations

import base64
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import requests

from core.barreiras import Barreira
from core.barreiras_geojson import (
    barreiras_de_geojson,
    geojson_de_barreiras,
    geojson_para_texto,
    texto_para_geojson,
)
from core.erros import ErroExterno
from core.ors import TIMEOUT_S

GITHUB_API = "https://api.github.com"


@dataclass(frozen=True)
class ConfigGitHub:
    token: str
    repo: str  # owner/nome
    path: str = "dados/barreiras.geojson"
    branch: str = "main"


class BarreirasStore(ABC):
    @abstractmethod
    def listar(self) -> list[Barreira]:
        raise NotImplementedError

    @abstractmethod
    def salvar_todas(self, barreiras: list[Barreira], *, mensagem: str) -> None:
        raise NotImplementedError

    def obter(self, barreira_id: str) -> Barreira | None:
        for barreira in self.listar():
            if barreira.id == barreira_id:
                return barreira
        return None

    def criar(self, barreira: Barreira, *, mensagem: str = "Cadastro: nova barreira") -> None:
        barreiras = self.listar()
        if any(b.id == barreira.id for b in barreiras):
            raise ErroExterno(f"Já existe barreira com id {barreira.id!r}")
        barreiras.append(barreira)
        self.salvar_todas(barreiras, mensagem=mensagem)

    def atualizar(self, barreira: Barreira, *, mensagem: str = "Cadastro: atualizar barreira") -> None:
        barreiras = self.listar()
        for i, atual in enumerate(barreiras):
            if atual.id == barreira.id:
                barreiras[i] = barreira
                self.salvar_todas(barreiras, mensagem=mensagem)
                return
        raise ErroExterno(f"Barreira {barreira.id!r} não encontrada")

    def remover(self, barreira_id: str, *, mensagem: str = "Cadastro: remover barreira") -> None:
        barreiras = self.listar()
        novas = [b for b in barreiras if b.id != barreira_id]
        if len(novas) == len(barreiras):
            raise ErroExterno(f"Barreira {barreira_id!r} não encontrada")
        if not novas:
            raise ErroExterno("Não é permitido remover todas as barreiras — o cadastro ficaria vazio.")
        self.salvar_todas(novas, mensagem=mensagem)


class ArquivoBarreirasStore(BarreirasStore):
    def __init__(self, caminho: str | Path) -> None:
        self.caminho = Path(caminho)

    def listar(self) -> list[Barreira]:
        if not self.caminho.exists():
            return []
        texto = self.caminho.read_text(encoding="utf-8")
        return barreiras_de_geojson(texto_para_geojson(texto))

    def salvar_todas(self, barreiras: list[Barreira], *, mensagem: str) -> None:
        if not barreiras:
            raise ErroExterno("Cadastro vazio não pode ser gravado.")
        colecao = geojson_de_barreiras(barreiras)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self.caminho.write_text(geojson_para_texto(colecao), encoding="utf-8")


class GitHubBarreirasStore(BarreirasStore):
    """Grava o GeoJSON no repositório via GitHub Contents API (persiste entre deploys)."""

    def __init__(self, config: ConfigGitHub) -> None:
        self.config = config
        self._sha: str | None = None

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _ler_remoto(self) -> tuple[dict, str]:
        url = f"{GITHUB_API}/repos/{self.config.repo}/contents/{self.config.path}"
        try:
            resp = requests.get(
                url,
                headers=self._headers(),
                params={"ref": self.config.branch},
                timeout=TIMEOUT_S,
            )
        except requests.RequestException as e:
            raise ErroExterno(f"GitHub indisponível: {e}") from e
        if resp.status_code == 404:
            raise ErroExterno(
                f"Arquivo {self.config.path!r} não encontrado em {self.config.repo} "
                f"(branch {self.config.branch})."
            )
        if resp.status_code != 200:
            raise ErroExterno(f"GitHub indisponível (HTTP {resp.status_code}). Tente novamente.")
        dados = resp.json()
        conteudo = base64.b64decode(dados["content"]).decode("utf-8")
        return texto_para_geojson(conteudo), dados["sha"]

    def listar(self) -> list[Barreira]:
        colecao, sha = self._ler_remoto()
        self._sha = sha
        return barreiras_de_geojson(colecao)

    def salvar_todas(self, barreiras: list[Barreira], *, mensagem: str) -> None:
        if not barreiras:
            raise ErroExterno("Cadastro vazio não pode ser gravado.")
        if self._sha is None:
            _, self._sha = self._ler_remoto()
        colecao = geojson_de_barreiras(barreiras)
        corpo_base = {
            "message": mensagem,
            "content": base64.b64encode(geojson_para_texto(colecao).encode("utf-8")).decode("ascii"),
            "branch": self.config.branch,
        }
        url = f"{GITHUB_API}/repos/{self.config.repo}/contents/{self.config.path}"

        for tentativa in range(2):
            corpo = {**corpo_base, "sha": self._sha}
            try:
                resp = requests.put(url, headers=self._headers(), json=corpo, timeout=TIMEOUT_S)
            except requests.RequestException as e:
                raise ErroExterno(f"GitHub indisponível ao gravar: {e}") from e
            if resp.status_code in (200, 201):
                self._sha = resp.json()["content"]["sha"]
                return
            if resp.status_code == 409 and tentativa == 0:
                _, self._sha = self._ler_remoto()
                continue
            raise ErroExterno(
                "Não foi possível gravar no GitHub "
                f"(HTTP {resp.status_code}). "
                "Outra edição pode ter ocorrido — recarregue a página e tente de novo."
            )


def _config_github() -> ConfigGitHub | None:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPO", "").strip()
    path = os.environ.get("GITHUB_BARREIRAS_PATH", "dados/barreiras.geojson").strip()
    branch = os.environ.get("GITHUB_BRANCH", "main").strip()
    try:
        import streamlit as st

        secao = st.secrets.get("github_barreiras")
        if secao:
            token = str(secao.get("token") or token).strip()
            repo = str(secao.get("repo") or repo).strip()
            path = str(secao.get("path") or path).strip()
            branch = str(secao.get("branch") or branch).strip()
    except Exception:
        pass
    if token and repo:
        return ConfigGitHub(token=token, repo=repo, path=path, branch=branch)
    return None


def obter_store(caminho_arquivo: str | Path) -> BarreirasStore:
    """
    GitHub quando configurado nos Secrets; senão arquivo local (dev/testes).

    No Streamlit Cloud o arquivo local é efêmero — configure ``[github_barreiras]``.
    """
    github = _config_github()
    if github:
        return GitHubBarreirasStore(github)
    return ArquivoBarreirasStore(caminho_arquivo)


def descricao_store(store: BarreirasStore) -> str:
    if isinstance(store, GitHubBarreirasStore):
        return f"GitHub ({store.config.repo}/{store.config.path})"
    if isinstance(store, ArquivoBarreirasStore):
        return f"arquivo local ({store.caminho})"
    return "desconhecido"
