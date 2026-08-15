"""Geocodificação via Nominatim (OpenStreetMap) — melhor para endereços no Brasil."""

from __future__ import annotations

import re
import threading
import time

import requests

from core.endereco_maps import (
    EnderecoMaps,
    Local,
    MUNICIPIO,
    _candidato_tem_endereco,
    pontuar_candidato,
)
from core.ors import TIMEOUT_S

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "barreiras-trajeto-mvp/1.0 (elegibilidade transporte escolar SP)"
# Política de uso do Nominatim: no máximo 1 requisição por segundo.
_INTERVALO_MIN_S = 1.1
_lock = threading.Lock()
_ultima_requisicao = 0.0
_bloqueado_ate = 0.0


class NominatimRateLimited(Exception):
    """Nominatim respondeu 429 — o chamador deve usar outro provedor."""


def _aguardar_intervalo() -> None:
    global _ultima_requisicao
    with _lock:
        agora = time.monotonic()
        if agora < _bloqueado_ate:
            time.sleep(_bloqueado_ate - agora)
            agora = time.monotonic()
        espera = _INTERVALO_MIN_S - (agora - _ultima_requisicao)
        if espera > 0:
            time.sleep(espera)
        _ultima_requisicao = time.monotonic()


def _cidade_sp(addr: dict) -> bool:
    for campo in ("city", "town", "municipality", "county"):
        valor = addr.get(campo) or ""
        if valor and MUNICIPIO.lower() in valor.lower():
            return True
    return False


def local_de_nominatim(
    resultado: dict, consulta: str, endereco: EnderecoMaps
) -> Local | None:
    """Converte uma resposta do Nominatim em `Local`, ou None se for irrelevante."""
    addr = resultado.get("address") or {}
    if addr and not _cidade_sp(addr):
        display = (resultado.get("display_name") or "").lower()
        if MUNICIPIO.lower() not in display:
            return None

    tipo = (resultado.get("type") or "").lower()
    classe = (resultado.get("class") or "").lower()
    if classe in {"boundary", "place"} and tipo in {"city", "state", "country", "administrative"}:
        return None

    road = addr.get("road")
    housenumber = addr.get("house_number")
    props = {
        "label": resultado.get("display_name"),
        "street": road,
        "housenumber": housenumber,
        "postalcode": addr.get("postcode"),
        "neighbourhood": addr.get("suburb") or addr.get("neighbourhood"),
        "borough": addr.get("city_district"),
        "confidence": resultado.get("importance"),
        "layer": tipo,
        "name": addr.get("amenity") or road,
    }
    if not _candidato_tem_endereco(props):
        return None

    try:
        lat = float(resultado["lat"])
        lon = float(resultado["lon"])
    except (KeyError, TypeError, ValueError):
        return None

    return Local(
        texto_original=consulta,
        endereco_formatado=resultado.get("display_name") or "(sem rótulo)",
        lat=lat,
        lon=lon,
        confianca=resultado.get("importance"),
        adequacao=pontuar_candidato(props, endereco),
    )


def buscar_nominatim(consulta: str, *, limit: int = 8) -> list[dict]:
    """
    Consulta o Nominatim respeitando o intervalo mínimo entre requisições.

    Levanta `NominatimRateLimited` em HTTP 429 para o chamador cair no ORS
    sem mostrar erro técnico ao usuário.
    """
    global _bloqueado_ate
    params = {
        "q": consulta,
        "format": "json",
        "limit": limit,
        "countrycodes": "br",
        "addressdetails": 1,
    }
    _aguardar_intervalo()
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT_S,
        )
    except requests.RequestException as e:
        raise NominatimRateLimited(f"rede: {e}") from e
    if resp.status_code == 429:
        with _lock:
            _bloqueado_ate = time.monotonic() + 30.0
        raise NominatimRateLimited("HTTP 429")
    if resp.status_code != 200:
        raise NominatimRateLimited(f"HTTP {resp.status_code}")
    dados = resp.json()
    return dados if isinstance(dados, list) else []


def consulta_nominatim_principal(endereco: EnderecoMaps) -> str | None:
    """Uma única consulta, da mais específica possível — reduz chamadas à API."""
    if endereco.logradouro and endereco.numero and endereco.bairro:
        partes = [
            f"{endereco.numero} {endereco.logradouro}",
            endereco.bairro,
            MUNICIPIO,
            "SP",
        ]
        if endereco.cep:
            partes.append(endereco.cep)
        return ", ".join(partes)
    if endereco.texto:
        return endereco.texto.strip()
    return None


def consultas_nominatim(endereco: EnderecoMaps) -> list[str]:
    """Variações de consulta, da mais específica à mais ampla."""
    consultas: list[str] = []
    principal = consulta_nominatim_principal(endereco)
    if principal:
        consultas.append(principal)
    if endereco.texto and principal != endereco.texto.strip():
        consultas.append(endereco.texto.strip())
    vistos: set[str] = set()
    unicas: list[str] = []
    for consulta in consultas:
        chave = re.sub(r"\s+", " ", consulta.strip().lower())
        if chave and chave not in vistos:
            vistos.add(chave)
            unicas.append(consulta.strip())
    return unicas
