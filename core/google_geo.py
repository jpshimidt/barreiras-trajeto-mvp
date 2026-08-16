"""Geocodificação via Google Places API (New) e widget Autocomplete."""

from __future__ import annotations

import os
import re
from urllib.parse import parse_qs, unquote, urlparse

import requests

from core.endereco_maps import EnderecoMaps, Local, MUNICIPIO, parse_endereco_maps
from core.erros import ErroExterno
from core.ors import TIMEOUT_S

AUTOCOMPLETE_URL = "https://places.googleapis.com/v1/places:autocomplete"
PLACE_URL = "https://places.googleapis.com/v1/places"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
CENTRO_SP = (-23.5505, -46.6333)  # lat, lon


class PlacesApiNovaIndisponivel(Exception):
    """Places API (New) desabilitada ou sem permissão — usar Geocoding legado."""


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
    if resp.status_code in (401, 403):
        raise PlacesApiNovaIndisponivel(resp.text[:300])
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


def buscar_sugestoes_endereco(texto: str, api_key: str, *, limit: int = 5) -> list[dict]:
    """
    Sugestões para a UI — Places API (New) ou Geocoding legado como fallback.

    Cada item: ``{"id": str, "texto": str, "local": Local | None}``.
    Quando ``local`` já vem preenchido (fallback), não é preciso chamar Place Details.
    """
    endereco = parse_endereco_maps(texto)
    try:
        novas = autocomplete_sugestoes(texto, api_key, limit=limit)
        return [
            {"id": s["place_id"], "texto": s["texto"], "local": None, "place_id": s["place_id"]}
            for s in novas
        ]
    except PlacesApiNovaIndisponivel:
        pass

    locais = _geocode_legacy(texto, api_key, endereco)
    return [
        {
            "id": f"legacy-{i}-{round(loc.lat, 6)}-{round(loc.lon, 6)}",
            "texto": loc.endereco_formatado,
            "local": loc,
            "place_id": None,
        }
        for i, loc in enumerate(locais[:limit])
    ]


def geocodificar_google(texto: str, api_key: str, *, max_detalhes: int = 3) -> list[Local]:
    """Busca candidatos via Autocomplete + Place Details (API New), com fallback legado."""
    endereco = parse_endereco_maps(texto)
    try:
        sugestoes = autocomplete_sugestoes(texto, api_key, limit=max_detalhes)
    except PlacesApiNovaIndisponivel:
        return _geocode_legacy(texto, api_key, endereco)
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


def parece_link_maps(texto: str) -> bool:
    """True se o texto é um link do Google Maps (curto ou completo)."""
    t = texto.strip().lower()
    return any(
        trecho in t
        for trecho in (
            "google.com/maps",
            "maps.google.",
            "maps.app.goo.gl",
            "goo.gl/maps",
        )
    )


def extrair_nome_de_url_maps(url: str) -> str | None:
    """Nome do lugar no path (/place/…, /search/…) ou no parâmetro q=."""
    parsed = urlparse(url.strip())
    partes = [p for p in parsed.path.split("/") if p]
    for i, parte in enumerate(partes):
        if parte in ("place", "search") and i + 1 < len(partes):
            nome = unquote(partes[i + 1].replace("+", " ")).strip()
            if nome and not nome.startswith("@"):
                return nome
    qs = parse_qs(parsed.query)
    for chave in ("q", "query"):
        valores = qs.get(chave) or []
        if not valores:
            continue
        valor = unquote(valores[0].replace("+", " ")).strip()
        if valor and not re.match(r"^-?\d+\.?\d*\s*,\s*-?\d+", valor):
            return valor
    return None


def extrair_coordenadas_maps_url(url: str) -> tuple[float, float] | None:
    """Extrai lat/lon de links compartilhados do Google Maps."""
    match = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", url)
    if match:
        return float(match.group(1)), float(match.group(2))
    match = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", url)
    if match:
        return float(match.group(1)), float(match.group(2))
    match = re.search(r"[?&]q=(-?\d+\.\d+),(-?\d+\.\d+)", url)
    if match:
        return float(match.group(1)), float(match.group(2))
    return None


def resolver_link_maps(url: str, sessao: requests.Session | None = None) -> str:
    """Segue redirecionamentos de links curtos (maps.app.goo.gl)."""
    sessao = sessao or requests.Session()
    try:
        resp = sessao.get(
            url,
            allow_redirects=True,
            timeout=TIMEOUT_S,
            headers={"User-Agent": "barreiras-trajeto-mvp/0.1 (cadastro de barreiras)"},
        )
        return str(resp.url or url)
    except requests.RequestException:
        return url


def geocode_reverso(lat: float, lon: float, api_key: str) -> str | None:
    """Endereço formatado a partir de uma coordenada (Geocoding legado)."""
    try:
        resp = requests.get(
            GEOCODE_URL,
            params={
                "latlng": f"{lat},{lon}",
                "key": api_key,
                "language": "pt-BR",
                "result_type": "route|street_address",
            },
            timeout=TIMEOUT_S,
        )
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    dados = resp.json()
    if dados.get("status") != "OK":
        return None
    for resultado in dados.get("results") or []:
        formatado = (resultado.get("formatted_address") or "").strip()
        if formatado:
            return formatado
    return None


def geocode_ponto(consulta: str, api_key: str) -> tuple[float, float] | None:
    """Primeiro ponto do Geocoding legado para um texto livre."""
    try:
        resp = requests.get(
            GEOCODE_URL,
            params={
                "address": consulta,
                "key": api_key,
                "components": "country:BR|administrative_area:SP|locality:São Paulo",
                "language": "pt-BR",
            },
            timeout=TIMEOUT_S,
        )
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    dados = resp.json()
    if dados.get("status") != "OK":
        return None
    loc = ((dados.get("results") or [{}])[0].get("geometry") or {}).get("location") or {}
    if loc.get("lat") is None or loc.get("lng") is None:
        return None
    return float(loc["lat"]), float(loc["lng"])


def pin_de_link_maps(
    url: str, sessao: requests.Session | None = None
) -> tuple[float, float]:
    """
    Pino (lat, lon) de um link do Maps.

    Usa coordenadas do próprio URL; se for link curto, segue o redirect;
    se só houver nome do lugar, geocodifica.
    """
    url = url.strip()
    if not url:
        raise ErroExterno("Cole o link do Google Maps.")
    coords = extrair_coordenadas_maps_url(url)
    if coords:
        return coords
    final = resolver_link_maps(url, sessao)
    coords = extrair_coordenadas_maps_url(final)
    if coords:
        return coords
    nome = extrair_nome_de_url_maps(final) or extrair_nome_de_url_maps(url)
    api_key = ler_google_api_key()
    if nome and api_key:
        ponto = geocode_ponto(nome, api_key)
        if ponto:
            return ponto
    raise ErroExterno(
        "Não achei um ponto neste link do Google Maps. "
        "Abra o lugar, copie o link compartilhado e cole de novo."
    )


def endereco_de_link_maps(url: str, sessao: requests.Session | None = None) -> str:
    """
    Converte link do Google Maps em endereço/nome de rua.

    Links completos (`/place/R.+Cruz+de+Malta…`) não precisam de rede.
    Links curtos (`maps.app.goo.gl`) seguem o redirecionamento.
    Se só houver coordenadas, faz geocode reverso.
    """
    url = url.strip()
    nome = extrair_nome_de_url_maps(url)
    if nome:
        return nome

    final = resolver_link_maps(url, sessao)
    nome = extrair_nome_de_url_maps(final)
    if nome:
        return nome

    coords = extrair_coordenadas_maps_url(final) or extrair_coordenadas_maps_url(url)
    if coords:
        api_key = ler_google_api_key()
        if api_key:
            reverso = geocode_reverso(coords[0], coords[1], api_key)
            if reverso:
                return reverso
        return f"{coords[0]}, {coords[1]}"

    raise ErroExterno(
        "Não consegui ler a rua neste link do Google Maps. "
        "Abra o lugar no Maps, copie o link completo (ou o endereço) e cole de novo."
    )
