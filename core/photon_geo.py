"""Geocodificação via Photon (Komoot/OSM) — fallback quando Nominatim limita."""

from __future__ import annotations

import requests

from core.endereco_maps import (
    EnderecoMaps,
    Local,
    MUNICIPIO,
    _candidato_tem_endereco,
    _completar_local,
    pontuar_candidato,
)
from core.ors import TIMEOUT_S

PHOTON_URL = "https://photon.komoot.io/api/"
USER_AGENT = "barreiras-trajeto-mvp/1.0 (elegibilidade transporte escolar SP)"


def local_de_photon(feature: dict, consulta: str, endereco: EnderecoMaps) -> Local | None:
    props = feature.get("properties") or {}
    cidade = props.get("city") or props.get("locality") or ""
    if cidade and MUNICIPIO.lower() not in cidade.lower():
        return None

    street = props.get("street") or props.get("name")
    housenumber = props.get("housenumber")
    osm_value = (props.get("osm_value") or props.get("type") or "").lower()
    label_parts = [
        p
        for p in (
            f"{housenumber} {street}".strip() if housenumber or street else None,
            props.get("district"),
            props.get("city"),
            props.get("state"),
            props.get("country"),
        )
        if p
    ]
    props_norm = {
        "label": ", ".join(label_parts) or consulta,
        "street": street,
        "housenumber": housenumber,
        "postalcode": props.get("postcode"),
        "neighbourhood": props.get("district"),
        "borough": props.get("city"),
        "confidence": 0.7,
        "layer": osm_value or "address",
        "name": props.get("name") or street,
    }
    if not _candidato_tem_endereco(props_norm):
        return None

    coords = (feature.get("geometry") or {}).get("coordinates")
    if not coords or len(coords) < 2:
        return None
    lon, lat = coords[0], coords[1]

    return _completar_local(
        Local(
            texto_original=consulta,
            endereco_formatado=props_norm["label"],
            lat=float(lat),
            lon=float(lon),
            confianca=0.7,
            adequacao=pontuar_candidato(props_norm, endereco),
        ),
        endereco,
        props_norm,
    )


def buscar_photon(consulta: str, *, limit: int = 8) -> list[dict]:
    params = {"q": consulta, "limit": limit, "lang": "default"}
    try:
        resp = requests.get(
            PHOTON_URL,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT_S,
        )
    except requests.RequestException:
        return []
    if resp.status_code != 200:
        return []
    dados = resp.json()
    return dados.get("features") or []


def consultas_photon(endereco: EnderecoMaps) -> list[str]:
    """Variações de consulta para o Photon — expande abreviações como R."""
    from core.nominatim_geo import consulta_nominatim_principal

    consultas: list[str] = []
    principal = consulta_nominatim_principal(endereco)
    if principal:
        consultas.append(principal)
    if endereco.logradouro and endereco.numero and endereco.bairro:
        logradouro = endereco.logradouro
        if logradouro.lower().startswith("r."):
            logradouro = "Rua" + logradouro[2:]
        consultas.append(
            ", ".join(
                [
                    f"{endereco.numero} {logradouro}",
                    endereco.bairro,
                    MUNICIPIO,
                    "SP",
                    endereco.cep or "",
                ]
            ).strip(", ")
        )
    if endereco.texto:
        consultas.append(endereco.texto.strip())
    vistos: set[str] = set()
    unicas: list[str] = []
    for consulta in consultas:
        chave = consulta.strip().lower()
        if chave and chave not in vistos:
            vistos.add(chave)
            unicas.append(consulta.strip())
    return unicas


def consulta_photon(endereco: EnderecoMaps) -> str | None:
    consultas = consultas_photon(endereco)
    return consultas[0] if consultas else None
