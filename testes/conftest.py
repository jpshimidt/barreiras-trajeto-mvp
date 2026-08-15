"""
Nenhum teste pode chamar a API.

O plano manda cobrir a tabela de decisão com geometrias sintéticas, sem rede: um
teste que depende do OpenRouteService falha quando a cota estoura ou o serviço cai,
e aí a suíte deixa de dizer se a REGRA está certa. Aqui a rede é bloqueada de vez —
quem esquecer de montar a resposta à mão recebe um erro explícito.
"""

import socket

import pytest


@pytest.fixture(autouse=True)
def sem_rede(monkeypatch):
    def proibido(*args, **kwargs):
        raise RuntimeError(
            "Este teste tentou abrir conexão de rede. "
            "Monte a resposta da API à mão em vez de chamar o serviço."
        )

    monkeypatch.setattr(socket, "socket", proibido)
    monkeypatch.setattr(socket, "create_connection", proibido)
