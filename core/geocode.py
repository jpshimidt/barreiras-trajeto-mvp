"""
Endereço em texto -> coordenada, restrito a São Paulo capital.

São Paulo tem 96 distritos e milhares de nomes de rua repetidos entre eles.
Duas defesas contra o pin cair no distrito errado:

1. o CEP entra no texto enviado ao geocodificador;
2. quando dois candidatos têm score próximo, quem chama DEVE mostrar a lista
   em vez de escolher sozinho (`candidatos_ambiguos`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import requests

from core.erros import ErroExterno
from core.ors import TIMEOUT_S, erro_http

MUNICIPIO = "São Paulo"
CENTRO_SP = (-46.6333, -23.5505)  # (lon, lat) — focus.point
MARGEM_EMPATE_CONFIANCA = 0.10
MAX_CANDIDATOS = 5
CEP_RE = re.compile(r"\b(\d{5})-?(\d{3})\b")
# Padrão Google Maps: R. Exemplo, 355 - Bairro, São Paulo - SP, 00000-000
EXEMPLO_ENDERECO_MAPS = "R. Voluntários da Pátria, 1000 - Santana, São Paulo - SP, 02011-000"

URL = "https://api.openrouteservice.org/geocode/search"


@dataclass
class Local:
    texto_original: str
    endereco_formatado: str  # o que o geocodificador entendeu — mostrar ao usuário
    lat: float
    lon: float
    confianca: float | None


def extrair_cep(texto: str) -> str | None:
    """Extrai CEP no formato 00000-000 de um endereço colado."""
    match = CEP_RE.search(texto)
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2)}"


def _cep_presente(texto: str, cep: str) -> bool:
    return re.sub(r"\D", "", cep) in re.sub(r"\D", "", texto)


def parse_endereco_maps(texto: str) -> tuple[str, str | None]:
    """
    Normaliza endereço colado no padrão Google Maps.

    Ex.: R. Ana Soares Barcelos, 355 - Vila Venditti, São Paulo - SP, 07031-070
    """
    texto = " ".join(texto.strip().split())
    return texto, extrair_cep(texto)


def montar_consulta(texto: str, cep: str | None = None) -> str:
    """
    Monta a consulta ao geocodificador.

    Aceita endereço no padrão Google Maps (com CEP no final) ou texto livre com
    CEP passado separadamente.
    """
    texto, cep_do_texto = parse_endereco_maps(texto)
    cep = (cep or cep_do_texto or "").strip() or None
    if cep and not _cep_presente(texto, cep):
        return f"{texto}, {cep}"
    return texto


def _candidato_tem_endereco(props: dict) -> bool:
    """Descarta resultados genéricos como 'São Paulo, Brazil' sem rua ou número."""
    if props.get("housenumber") or props.get("street"):
        return True
    layer = (props.get("layer") or "").lower()
    return layer in {"address", "street", "venue"}


def local_de_feature(feature: dict, texto_original: str) -> Local | None:
    """
    Converte uma feature do Pelias em `Local`, ou None se não for de São Paulo capital.

    `locality` é o município no Pelias. Quando ele vem preenchido e é outra cidade,
    o candidato é descartado — homônimo de rua em Guarulhos não pode virar decisão.
    Quando vem vazio, o candidato passa: filtrar demais custaria endereços válidos,
    e o endereço formatado ainda é exibido para conferência.
    """
    props = feature.get("properties") or {}
    locality = props.get("locality")
    if locality and MUNICIPIO.lower() not in locality.lower():
        return None
    if not _candidato_tem_endereco(props):
        return None

    coords = (feature.get("geometry") or {}).get("coordinates")
    if not coords or len(coords) < 2:
        return None

    lon, lat = coords[0], coords[1]
    return Local(
        texto_original=texto_original,
        endereco_formatado=props.get("label") or "(sem rótulo)",
        lat=float(lat),
        lon=float(lon),
        confianca=props.get("confidence"),
    )


def candidatos_ambiguos(
    candidatos: list[Local], margem: float = MARGEM_EMPATE_CONFIANCA
) -> list[Local]:
    """
    Candidatos que empatam com o primeiro dentro da margem de confiança.

    Lista não vazia = a interface tem de mostrar as opções em vez de decidir sozinha.
    """
    if len(candidatos) < 2:
        return []
    melhor = candidatos[0]
    if melhor.confianca is None:
        return []
    return [
        c
        for c in candidatos[1:]
        if c.confianca is not None and melhor.confianca - c.confianca <= margem
    ]


def geocodificar(texto: str, api_key: str, cep: str | None = None) -> list[Local]:
    """Candidatos ordenados por confiança, restritos a São Paulo capital."""
    consulta = montar_consulta(texto, cep)
    params = {
        "api_key": api_key,
        "text": consulta,
        "boundary.country": "BR",
        "focus.point.lon": CENTRO_SP[0],
        "focus.point.lat": CENTRO_SP[1],
        "layers": "address,venue,street",
        "size": MAX_CANDIDATOS,
    }
    try:
        resp = requests.get(URL, params=params, timeout=TIMEOUT_S)
    except requests.RequestException as e:
        raise ErroExterno(f"Geocodificação falhou na rede: {e}") from e
    if resp.status_code != 200:
        raise erro_http(resp, "Geocodificação")

    locais = [
        local
        for feature in (resp.json().get("features") or [])
        if (local := local_de_feature(feature, consulta)) is not None
    ]
    if not locais:
        raise ErroExterno(
            f"Nenhum endereço em {MUNICIPIO} para: {consulta!r}\n"
            f"  Cole o endereço como no Google Maps, por exemplo:\n"
            f"  {EXEMPLO_ENDERECO_MAPS}"
        )
    return locais
