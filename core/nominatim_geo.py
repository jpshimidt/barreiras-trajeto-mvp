"""Geocodificação via Nominatim (OpenStreetMap) — melhor para endereços no Brasil."""

from __future__ import annotations

import re

import requests

from core.endereco_maps import (
    EnderecoMaps,
    Local,
    MUNICIPIO,
    _candidato_tem_endereco,
    pontuar_candidato,
)
from core.erros import ErroExterno
from core.ors import TIMEOUT_S

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "barreiras-trajeto-mvp/1.0 (elegibilidade transporte escolar SP)"


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
    params = {
        "q": consulta,
        "format": "json",
        "limit": limit,
        "countrycodes": "br",
        "addressdetails": 1,
    }
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT_S,
        )
    except requests.RequestException as e:
        raise ErroExterno(f"Geocodificação (Nominatim) falhou na rede: {e}") from e
    if resp.status_code != 200:
        raise ErroExterno(
            f"Geocodificação (Nominatim) respondeu HTTP {resp.status_code} — {resp.text[:200]}"
        )
    dados = resp.json()
    return dados if isinstance(dados, list) else []


def consultas_nominatim(endereco: EnderecoMaps) -> list[str]:
    """Variações de consulta, da mais específica à mais ampla."""
    consultas: list[str] = []
    if endereco.texto:
        consultas.append(endereco.texto)
    if endereco.logradouro and endereco.numero and endereco.bairro:
        partes = [
            f"{endereco.numero} {endereco.logradouro}",
            endereco.bairro,
            MUNICIPIO,
            "SP",
        ]
        if endereco.cep:
            partes.append(endereco.cep)
        consultas.append(", ".join(partes))
        consultas.append(
            ", ".join([endereco.logradouro, endereco.numero, endereco.bairro, MUNICIPIO, "SP"])
        )
    vistos: set[str] = set()
    unicas: list[str] = []
    for consulta in consultas:
        chave = re.sub(r"\s+", " ", consulta.strip().lower())
        if chave and chave not in vistos:
            vistos.add(chave)
            unicas.append(consulta.strip())
    return unicas
