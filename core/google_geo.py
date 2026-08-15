"""Geocodificação via Google Places API (New) e widget Autocomplete."""

from __future__ import annotations

import os
import re

import requests

from core.endereco_maps import EnderecoMaps, Local, MUNICIPIO, parse_endereco_maps
from core.erros import ErroExterno
from core.ors import TIMEOUT_S

AUTOCOMPLETE_URL = "https://places.googleapis.com/v1/places:autocomplete"
PLACE_URL = "https://places.googleapis.com/v1/places"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
CENTRO_SP = (-23.5505, -46.6333)  # lat, lon


def ler_google_api_key() -> str | None:
    """Chave para chamadas server-side (Places API, Geocoding). Nunca enviar ao navegador."""
    try:
        import streamlit as st

        if "GOOGLE_MAPS_API_KEY" in st.secrets:
            chave = str(st.secrets["GOOGLE_MAPS_API_KEY"]).strip()
            if chave:
                return chave
    except Exception:
        pass
    chave = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    return chave or None


def ler_google_maps_js_key() -> str | None:
    """
    Chave restrita por HTTP referrer para o widget Autocomplete no navegador.

    Use uma chave separada da server-side e restrinja a ``*.streamlit.app``.
    """
    try:
        import streamlit as st

        if "GOOGLE_MAPS_JS_KEY" in st.secrets:
            chave = str(st.secrets["GOOGLE_MAPS_JS_KEY"]).strip()
            if chave:
                return chave
    except Exception:
        pass
    chave = os.environ.get("GOOGLE_MAPS_JS_KEY", "").strip()
    return chave or None


def chave_google_para_widget() -> str | None:
    """Chave Maps JavaScript — nunca usar a chave server-side no navegador."""
    return ler_google_maps_js_key()


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
    }


def _numero_dos_componentes(components: list[dict]) -> tuple[str | None, str | None]:
    numero = rua = None
    for comp in components:
        tipos = comp.get("types") or []
        if "street_number" in tipos:
            numero = comp.get("longText") or comp.get("shortText")
        if "route" in tipos:
            rua = comp.get("longText") or comp.get("shortText")
    return numero, rua


def local_de_place_details(dados: dict, consulta: str, endereco: EnderecoMaps | None) -> Local:
    location = dados.get("location") or {}
    lat = float(location.get("latitude", 0))
    lon = float(location.get("longitude", 0))
    formatted = dados.get("formattedAddress") or dados.get("displayName", {}).get("text") or consulta
    components = dados.get("addressComponents") or []
    numero_api, rua_api = _numero_dos_componentes(components)

    numero_informado = endereco.numero if endereco else None
    numero_confirmado = True
    if numero_informado:
        numero_confirmado = bool(numero_api and numero_api == numero_informado)

    return Local(
        texto_original=consulta,
        endereco_formatado=formatted,
        lat=lat,
        lon=lon,
        confianca=1.0,
        adequacao=100 if numero_confirmado else 70,
        numero_informado=numero_informado,
        numero_confirmado=numero_confirmado,
    )


def local_de_selecao_widget(dados: dict, consulta: str = "") -> Local:
    """Converte o retorno do widget Autocomplete (Maps JavaScript API) em Local."""
    endereco = parse_endereco_maps(consulta or dados.get("formatted_address", ""))
    numero_google = (dados.get("number") or "").strip() or None
    numero_informado = endereco.numero or numero_google

    if endereco.numero and numero_google:
        numero_confirmado = endereco.numero == numero_google
    elif endereco.numero and not numero_google:
        numero_confirmado = False
    elif numero_google:
        numero_confirmado = True
    else:
        numero_confirmado = True

    return Local(
        texto_original=consulta or dados.get("formatted_address", ""),
        endereco_formatado=dados.get("formatted_address") or "(sem rótulo)",
        lat=float(dados["lat"]),
        lon=float(dados["lon"]),
        confianca=1.0,
        adequacao=100 if numero_confirmado else 75,
        numero_informado=numero_informado,
        numero_confirmado=numero_confirmado,
    )


def detalhes_place_id(place_id: str, api_key: str, consulta: str, endereco: EnderecoMaps | None) -> Local:
    resp = requests.get(
        f"{PLACE_URL}/{place_id}",
        headers={
            **_headers(api_key),
            "X-Goog-FieldMask": "formattedAddress,location,addressComponents,displayName",
        },
        timeout=TIMEOUT_S,
    )
    if resp.status_code != 200:
        raise ErroExterno(f"Google Places respondeu HTTP {resp.status_code} — {resp.text[:200]}")
    return local_de_place_details(resp.json(), consulta, endereco)


def autocomplete_sugestoes(texto: str, api_key: str, *, limit: int = 5) -> list[dict]:
    corpo = {
        "input": texto,
        "includedRegionCodes": ["br"],
        "languageCode": "pt-BR",
        "locationBias": {
            "circle": {
                "center": {"latitude": CENTRO_SP[0], "longitude": CENTRO_SP[1]},
                "radius": 50000.0,
            }
        },
    }
    try:
        resp = requests.post(AUTOCOMPLETE_URL, headers=_headers(api_key), json=corpo, timeout=TIMEOUT_S)
    except requests.RequestException as e:
        raise ErroExterno(f"Google Autocomplete falhou na rede: {e}") from e
    if resp.status_code != 200:
        raise ErroExterno(f"Google Autocomplete respondeu HTTP {resp.status_code} — {resp.text[:200]}")
    sugestoes = []
    for item in resp.json().get("suggestions") or []:
        pred = item.get("placePrediction") or {}
        place_id = pred.get("placeId")
        texto_sug = (pred.get("text") or {}).get("text")
        if place_id and texto_sug:
            sugestoes.append({"place_id": place_id, "texto": texto_sug})
        if len(sugestoes) >= limit:
            break
    return sugestoes


def geocodificar_google(texto: str, api_key: str, *, max_detalhes: int = 3) -> list[Local]:
    """Busca candidatos via Autocomplete + Place Details (API New)."""
    endereco = parse_endereco_maps(texto)
    sugestoes = autocomplete_sugestoes(texto, api_key, limit=max_detalhes)
    if not sugestoes:
        return _geocode_legacy(texto, api_key, endereco)

    locais: list[Local] = []
    for sug in sugestoes[:max_detalhes]:
        local = detalhes_place_id(sug["place_id"], api_key, texto, endereco)
        locais.append(local)
    return locais


def _geocode_legacy(texto: str, api_key: str, endereco: EnderecoMaps) -> list[Local]:
    params = {
        "address": texto,
        "key": api_key,
        "components": "country:BR|administrative_area:SP|locality:São Paulo",
        "language": "pt-BR",
    }
    try:
        resp = requests.get(GEOCODE_URL, params=params, timeout=TIMEOUT_S)
    except requests.RequestException as e:
        raise ErroExterno(f"Google Geocoding falhou na rede: {e}") from e
    if resp.status_code != 200:
        raise ErroExterno(f"Google Geocoding respondeu HTTP {resp.status_code}")
    dados = resp.json()
    if dados.get("status") != "OK":
        raise ErroExterno(
            f"Nenhum endereço em {MUNICIPIO} para: {texto!r} (Google: {dados.get('status')})"
        )
    locais: list[Local] = []
    for resultado in dados.get("results") or []:
        loc = resultado.get("geometry", {}).get("location", {})
        components = []
        for comp in resultado.get("address_components") or []:
            components.append(
                {
                    "types": comp.get("types"),
                    "longText": comp.get("long_name"),
                    "shortText": comp.get("short_name"),
                }
            )
        numero, _ = _numero_dos_componentes(components)
        widget = {
            "formatted_address": resultado.get("formatted_address"),
            "lat": loc.get("lat"),
            "lon": loc.get("lng"),
            "number": numero,
        }
        if widget["lat"] is not None and widget["lon"] is not None:
            locais.append(local_de_selecao_widget(widget, texto))
    return locais


def extrair_coordenadas_maps_url(url: str) -> tuple[float, float] | None:
    """Extrai lat/lon de links compartilhados do Google Maps."""
    match = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", url)
    if match:
        return float(match.group(1)), float(match.group(2))
    match = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", url)
    if match:
        return float(match.group(1)), float(match.group(2))
    return None
