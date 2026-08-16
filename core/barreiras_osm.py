"""Busca de geometria de barreiras no OpenStreetMap (Overpass)."""

from __future__ import annotations

import os
import re
import time
import unicodedata
from datetime import date

import requests
from shapely.geometry import LineString

from core.barreiras import Barreira, TIPOS_BARREIRA
from core.barreiras_geojson import barreira_de_feature
from core.endereco_maps import parse_endereco_maps
from core.erros import ErroExterno
from core.recorte_trecho import (
    MarcaNumero,
    RegistroTrecho,
    marcas_de_coordenadas,
    recortar_linha_por_numeros,
)
from core.ors import TIMEOUT_S

MUNICIPIO = "São Paulo"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
NOMINATIM_LOOKUP = "https://nominatim.openstreetmap.org/lookup"
OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
)
USER_AGENT = "barreiras-trajeto-mvp/0.1 (cadastro de barreiras)"

# Relação OSM de São Paulo capital (admin_level=8) — constante documentada no README.
RELACAO_SP_PADRAO = 298285

TIMEOUT_CONSULTA_S = (8, 45)
TIMEOUT_OVERPASS_S = 40
TENTATIVAS = 2
DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"

class OverpassIndisponivel(ErroExterno):
    """Nenhum mirror Overpass respondeu — o chamador pode usar Nominatim."""


TIPOS_OSM = {
    "motorway": "rodovia",
    "motorway_link": "acesso de rodovia",
    "trunk": "via expressa",
    "trunk_link": "acesso de via expressa",
    "primary": "avenida",
    "primary_link": "acesso de avenida",
    "secondary": "avenida",
    "secondary_link": "acesso de avenida",
    "tertiary": "rua",
    "residential": "rua",
    "unclassified": "rua",
}


def area_id(relacao_id: int) -> int:
    return 3600000000 + relacao_id


def slug(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", sem_acento.lower()).strip("-")


_ABREV_VIA = (
    (re.compile(r"^R\.\s+", re.IGNORECASE), "Rua "),
    (re.compile(r"^Av\.\s+", re.IGNORECASE), "Avenida "),
    (re.compile(r"^Al\.\s+", re.IGNORECASE), "Alameda "),
    (re.compile(r"^Tv\.\s+", re.IGNORECASE), "Travessa "),
    (re.compile(r"^Pça\.\s+", re.IGNORECASE), "Praça "),
    (re.compile(r"^Rod\.\s+", re.IGNORECASE), "Rodovia "),
)


def expandir_abrev_via(nome: str) -> str:
    """R. / Av. → Rua / Avenida — grafia usual no OSM e no Google."""
    for padrao, subst in _ABREV_VIA:
        if padrao.match(nome):
            return padrao.sub(subst, nome, count=1)
    return nome


def nome_via_de_entrada(texto: str) -> str:
    """Extrai logradouro de endereço, link do Maps ou texto livre."""
    texto = texto.strip()
    if not texto:
        return ""
    from core.google_geo import extrair_nome_de_url_maps, parece_link_maps

    if parece_link_maps(texto):
        extraido = extrair_nome_de_url_maps(texto)
        if extraido:
            texto = extraido
    endereco = parse_endereco_maps(texto)
    nome = (endereco.logradouro or texto).strip()
    if parece_link_maps(nome):
        return ""
    return expandir_abrev_via(nome)


def montar_consulta(ruas: list[str], relacao_id: int, regex: bool = False) -> str:
    linhas = []
    for rua in ruas:
        nome = rua.replace('"', '\\"')
        if regex:
            linhas.append(f'  way(area.sp)["highway"]["name"~"{nome}",i];')
        else:
            linhas.append(f'  way(area.sp)["highway"]["name"="{nome}"];')
    corpo = "\n".join(linhas)
    return (
        f"[out:json][timeout:{TIMEOUT_OVERPASS_S}];\n"
        f"area({area_id(relacao_id)})->.sp;\n"
        f"(\n{corpo}\n);\n"
        f"out geom;\n"
    )


def feature_de_way(
    elemento: dict,
    importado_em: str,
    trecho: RegistroTrecho | None = None,
    marcas: list[MarcaNumero] | None = None,
) -> dict | None:
    geometria = elemento.get("geometry") or []
    if len(geometria) < 2:
        return None

    coords = [(p["lon"], p["lat"]) for p in geometria]
    linha = LineString(coords)
    trecho = trecho or RegistroTrecho(elemento.get("tags", {}).get("name") or "(sem nome)")

    if trecho.tem_faixa():
        if not marcas:
            return None
        recortada = recortar_linha_por_numeros(
            linha,
            marcas,
            trecho.numero_inicio,
            trecho.numero_fim,
            paridade=trecho.paridade,
        )
        if recortada is None or recortada.is_empty:
            return None
        linha = recortada
        coords = list(linha.coords)

    tags = elemento.get("tags") or {}
    nome = tags.get("name") or trecho.nome or "(sem nome)"
    osm_way_id = elemento.get("id")
    sufixo_trecho = ""
    if trecho.tem_faixa():
        sufixo_trecho = f"-{trecho.numero_inicio or 0}-{trecho.numero_fim or 0}"
        if trecho.paridade:
            sufixo_trecho += f"-{trecho.paridade}"

    props = {
        "id": f"{slug(nome)}-{osm_way_id}{sufixo_trecho}",
        "nome": nome,
        "tipo": TIPOS_OSM.get(tags.get("highway"), tags.get("highway") or "(sem tipo)"),
        "municipio": MUNICIPIO,
        "origem": "overpass",
        "osm_way_id": osm_way_id,
        "importado_em": importado_em,
    }
    if trecho.tem_faixa():
        props["numero_inicio"] = trecho.numero_inicio
        props["numero_fim"] = trecho.numero_fim
        if trecho.paridade:
            props["paridade"] = trecho.paridade

    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [list(c) for c in coords]},
        "properties": props,
    }


def overpass_para_geojson(
    resposta: dict,
    importado_em: str | None = None,
    trechos: list[RegistroTrecho] | None = None,
    marcas_por_way: dict[int, list[MarcaNumero]] | None = None,
) -> dict:
    importado_em = importado_em or date.today().isoformat()
    elementos = [e for e in (resposta.get("elements") or []) if e.get("type") == "way"]
    marcas_por_way = marcas_por_way or {}

    if not trechos:
        features = [
            feature
            for elemento in elementos
            if (feature := feature_de_way(elemento, importado_em)) is not None
        ]
        return {"type": "FeatureCollection", "name": "barreiras", "features": features}

    features: list[dict] = []
    for trecho in trechos:
        for elemento in elementos:
            nome_way = ((elemento.get("tags") or {}).get("name") or "").lower()
            alvo = trecho.nome.lower()
            if not (alvo in nome_way or nome_way in alvo):
                continue
            wid = elemento.get("id")
            marcas = marcas_por_way.get(wid, []) if trecho.tem_faixa() else None
            if trecho.tem_faixa() and not marcas:
                continue
            feature = feature_de_way(elemento, importado_em, trecho, marcas)
            if feature:
                features.append(feature)
    return {"type": "FeatureCollection", "name": "barreiras", "features": features}


def montar_consulta_numeros(way_ids: list[int]) -> str:
    if not way_ids:
        return ""
    ids = ",".join(str(w) for w in way_ids[:400])
    return (
        f"[out:json][timeout:120];\n"
        f"way(id:{ids});\n"
        f'node(w)["addr:housenumber"];\n'
        f"out body;\n"
    )


def indexar_numeros_por_way(
    resposta_ways: dict, resposta_numeros: dict
) -> dict[int, list[MarcaNumero]]:
    from shapely.geometry import Point

    ways: dict[int, LineString] = {}
    nos_do_way: dict[int, set[int]] = {}
    for el in resposta_ways.get("elements") or []:
        if el.get("type") != "way":
            continue
        geom = el.get("geometry") or []
        if len(geom) < 2:
            continue
        wid = el["id"]
        ways[wid] = LineString([(p["lon"], p["lat"]) for p in geom])
        nos_do_way[wid] = set(el.get("nodes") or [])

    nos: dict[int, tuple[int, float, float]] = {}
    for el in resposta_numeros.get("elements") or []:
        if el.get("type") != "node":
            continue
        tags = el.get("tags") or {}
        bruto = str(tags.get("addr:housenumber", "")).strip()
        if not bruto.isdigit():
            continue
        nos[el["id"]] = (int(bruto), el["lon"], el["lat"])

    marcas_por_way: dict[int, list[MarcaNumero]] = {}
    for wid, linha in ways.items():
        membros = nos_do_way.get(wid, set())
        pontos = [nos[nid] for nid in membros if nid in nos]
        if pontos:
            marcas_por_way[wid] = marcas_de_coordenadas(linha, pontos)
    return marcas_por_way


def contar_por_rua(geojson: dict) -> dict[str, int]:
    contagem: dict[str, int] = {}
    for feature in geojson["features"]:
        nome = feature["properties"]["nome"]
        contagem[nome] = contagem.get(nome, 0) + 1
    return contagem


def ruas_sem_resultado(pedidas: list[str], geojson: dict) -> list[str]:
    achados = [f["properties"]["nome"].lower() for f in geojson["features"]]
    faltando = []
    for rua in pedidas:
        alvo = rua.lower()
        if not any(alvo in achado or achado in alvo for achado in achados):
            faltando.append(rua)
    return faltando


def ler_overpass_urls() -> list[str]:
    """URLs Overpass: secret/env ``OVERPASS_URL`` primeiro, depois mirrors públicos."""
    custom: list[str] = []
    try:
        import streamlit as st

        if "OVERPASS_URL" in st.secrets:
            url = str(st.secrets["OVERPASS_URL"]).strip()
            if url:
                custom.append(url)
    except Exception:
        pass
    env = os.environ.get("OVERPASS_URL", "").strip()
    if env and env not in custom:
        custom.append(env)
    vistos: set[str] = set()
    urls: list[str] = []
    for url in [*custom, *OVERPASS_ENDPOINTS]:
        if url not in vistos:
            vistos.add(url)
            urls.append(url)
    return urls


def descobrir_relacao_sp(sessao: requests.Session) -> int:
    resp = sessao.get(
        NOMINATIM,
        params={
            "q": "São Paulo, SP, Brasil",
            "format": "json",
            "limit": 10,
            "extratags": 1,
            "addressdetails": 1,
        },
        timeout=60,
        headers={"User-Agent": USER_AGENT},
    )
    resp.raise_for_status()
    for r in resp.json():
        if r.get("osm_type") != "relation":
            continue
        if str((r.get("extratags") or {}).get("admin_level")) != "8":
            continue
        return int(r["osm_id"])
    raise ErroExterno(
        "Não foi possível descobrir a relação OSM de São Paulo. "
        f"Use a constante RELACAO_SP_PADRAO={RELACAO_SP_PADRAO}."
    )


def consultar_overpass(sessao: requests.Session, consulta: str) -> dict:
    """Consulta Overpass tentando mirrors em sequência."""
    erros: list[str] = []
    for url in ler_overpass_urls():
        espera = 5
        for tentativa in range(1, TENTATIVAS + 1):
            try:
                resp = sessao.post(
                    url,
                    data={"data": consulta},
                    timeout=TIMEOUT_CONSULTA_S,
                    headers={"User-Agent": USER_AGENT},
                )
            except requests.RequestException as e:
                erros.append(f"{url}: rede ({type(e).__name__})")
                break
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (429, 504) and tentativa < TENTATIVAS:
                time.sleep(espera)
                espera *= 2
                continue
            erros.append(f"{url}: HTTP {resp.status_code}")
            break
    resumo = "; ".join(erros[:4])
    if len(erros) > 4:
        resumo += f"; … (+{len(erros) - 4} mirrors)"
    raise OverpassIndisponivel(
        "Overpass indisponível em todos os mirrors. "
        f"Tentativas: {resumo or 'nenhuma URL configurada'}"
    )


def _coords_de_geometria_nominatim(geometria: dict) -> list[tuple[float, float]] | None:
    tipo = geometria.get("type")
    coords_bruto = geometria.get("coordinates")
    if not coords_bruto:
        return None
    if tipo == "LineString":
        linhas = [coords_bruto]
    elif tipo == "MultiLineString":
        linhas = coords_bruto
    elif tipo == "Polygon":
        linhas = [coords_bruto[0]]
    else:
        return None
    if not linhas:
        return None
    melhor = max(linhas, key=len)
    if len(melhor) < 2:
        return None
    return [(float(lon), float(lat)) for lon, lat in melhor]


def feature_de_nominatim(
    feature: dict,
    importado_em: str,
    trecho: RegistroTrecho | None = None,
) -> dict | None:
    coords = _coords_de_geometria_nominatim(feature.get("geometry") or {})
    if not coords:
        return None

    props_osm = feature.get("properties") or {}
    tags = props_osm.get("tags") or {}
    nome = (
        tags.get("name")
        or props_osm.get("name")
        or props_osm.get("display_name")
        or (trecho.nome if trecho else None)
        or "(sem nome)"
    )
    osm_id = props_osm.get("osm_id") or props_osm.get("place_id")
    highway = tags.get("highway") or props_osm.get("type") or ""
    tipo_via = TIPOS_OSM.get(highway, highway or "(sem tipo)")

    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [list(c) for c in coords]},
        "properties": {
            "id": f"{slug(nome)}-nominatim-{osm_id or slug(nome)}",
            "nome": nome,
            "tipo": tipo_via,
            "municipio": MUNICIPIO,
            "origem": "nominatim",
            "importado_em": importado_em,
        },
    }


def _nominatim_candidato_relevante(resultado: dict, nome_alvo: str) -> bool:
    addr = resultado.get("address") or {}
    display = (resultado.get("display_name") or "").lower()
    if MUNICIPIO.lower() not in display and not any(
        MUNICIPIO.lower() in str(addr.get(c) or "").lower()
        for c in ("city", "town", "municipality", "county", "state")
    ):
        return False
    if resultado.get("class") == "highway":
        return True
    road = (addr.get("road") or "").lower()
    alvo = nome_alvo.lower()
    return bool(road and (alvo in road or road in alvo))


def _osm_id_lookup(resultado: dict) -> str | None:
    tipo = (resultado.get("osm_type") or "").lower()
    osm_id = resultado.get("osm_id")
    if not osm_id:
        return None
    prefix = {"node": "N", "way": "W", "relation": "R"}.get(tipo)
    if not prefix:
        return None
    return f"{prefix}{osm_id}"


def buscar_features_nominatim(
    sessao: requests.Session,
    nome: str,
    trecho: RegistroTrecho | None = None,
) -> list[dict]:
    """Fallback quando Overpass está bloqueado — geometria via Nominatim lookup."""
    importado_em = date.today().isoformat()
    consultas = [
        f"{nome}, {MUNICIPIO}, SP, Brasil",
        nome,
    ]
    osm_ids: list[str] = []
    vistos: set[str] = set()
    for consulta in consultas:
        try:
            resp = sessao.get(
                NOMINATIM,
                params={
                    "q": consulta,
                    "format": "json",
                    "limit": 8,
                    "countrycodes": "br",
                    "addressdetails": 1,
                },
                timeout=60,
                headers={"User-Agent": USER_AGENT},
            )
        except requests.RequestException as e:
            raise ErroExterno(f"Nominatim falhou na rede: {e}") from e
        if resp.status_code != 200:
            continue
        for item in resp.json():
            if not _nominatim_candidato_relevante(item, nome):
                continue
            oid = _osm_id_lookup(item)
            if oid and oid not in vistos:
                vistos.add(oid)
                osm_ids.append(oid)
        if osm_ids:
            break

    if not osm_ids:
        return []

    try:
        resp = sessao.get(
            NOMINATIM_LOOKUP,
            params={
                "osm_ids": ",".join(osm_ids[:10]),
                "format": "geojson",
                "polygon_geojson": 1,
            },
            timeout=60,
            headers={"User-Agent": USER_AGENT},
        )
    except requests.RequestException as e:
        raise ErroExterno(f"Nominatim lookup falhou na rede: {e}") from e
    if resp.status_code != 200:
        raise ErroExterno(f"Nominatim lookup respondeu HTTP {resp.status_code}")

    colecao = resp.json()
    features: list[dict] = []
    alvo = (trecho.nome if trecho else nome).lower()
    for feature in colecao.get("features") or []:
        props = feature.get("properties") or {}
        nome_feat = (
            (props.get("tags") or {}).get("name")
            or props.get("name")
            or props.get("display_name")
            or ""
        ).lower()
        if nome_feat and alvo not in nome_feat and nome_feat not in alvo:
            continue
        convertida = feature_de_nominatim(feature, importado_em, trecho)
        if convertida:
            features.append(convertida)
    return features


def decodificar_polyline(encoded: str) -> list[tuple[float, float]]:
    """Polyline do Google Directions → [(lon, lat), ...]."""
    coords: list[tuple[float, float]] = []
    index = lat = lng = 0
    while index < len(encoded):
        for eixo in ("lat", "lng"):
            shift = result = 0
            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else (result >> 1)
            if eixo == "lat":
                lat += delta
            else:
                lng += delta
        coords.append((lng / 1e5, lat / 1e5))
    return coords


def feature_de_linha(
    coords: list[tuple[float, float]],
    nome: str,
    *,
    origem: str,
    tipo: str = "rua",
    importado_em: str | None = None,
) -> dict | None:
    if len(coords) < 2:
        return None
    importado_em = importado_em or date.today().isoformat()
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [list(c) for c in coords]},
        "properties": {
            "id": f"{slug(nome)}-{origem}",
            "nome": nome,
            "tipo": tipo,
            "municipio": MUNICIPIO,
            "origem": origem,
            "importado_em": importado_em,
        },
    }


def _geocode_google(api_key: str, consulta: str) -> dict | None:
    from core.google_geo import GEOCODE_URL

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
    resultados = dados.get("results") or []
    return resultados[0] if resultados else None


def _ponto_de_geocode(resultado: dict) -> tuple[float, float] | None:
    loc = (resultado.get("geometry") or {}).get("location") or {}
    if loc.get("lat") is None or loc.get("lng") is None:
        return None
    return float(loc["lat"]), float(loc["lng"])


def _extremos_de_viewport(resultado: dict) -> tuple[tuple[float, float], tuple[float, float]] | None:
    geom = resultado.get("geometry") or {}
    box = geom.get("bounds") or geom.get("viewport")
    if not box:
        return None
    sw, ne = box.get("southwest") or {}, box.get("northeast") or {}
    if None in (sw.get("lat"), sw.get("lng"), ne.get("lat"), ne.get("lng")):
        return None
    origem = (float(sw["lat"]), float(sw["lng"]))
    destino = (float(ne["lat"]), float(ne["lng"]))
    if origem == destino:
        return None
    return origem, destino


def _pontos_google_para_rota(
    api_key: str,
    nome: str,
    trecho: RegistroTrecho | None,
    entrada: str | None = None,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Dois pontos (lat, lon) nas extremidades da via, via Geocoding."""
    if trecho and trecho.tem_faixa():
        consultas = [
            f"{nome}, {trecho.numero_inicio}, {MUNICIPIO}, SP, Brasil",
            f"{nome}, {trecho.numero_fim}, {MUNICIPIO}, SP, Brasil",
        ]
        pontos: list[tuple[float, float]] = []
        for consulta in consultas:
            resultado = _geocode_google(api_key, consulta)
            ponto = _ponto_de_geocode(resultado) if resultado else None
            if not ponto:
                return None
            pontos.append(ponto)
        if pontos[0] == pontos[1]:
            return None
        return pontos[0], pontos[1]

    for consulta in (entrada, nome, f"{nome}, {MUNICIPIO}, SP, Brasil"):
        if not consulta:
            continue
        resultado = _geocode_google(api_key, consulta)
        if not resultado:
            continue
        extremos = _extremos_de_viewport(resultado)
        if extremos:
            return extremos
    return None


def directions_entre_pontos(
    origem: tuple[float, float],
    destino: tuple[float, float],
    api_key: str | None = None,
) -> list[tuple[float, float]]:
    """Caminho entre dois (lat, lon) → coordenadas (lon, lat). Google, depois ORS."""
    if api_key:
        try:
            resp = requests.get(
                DIRECTIONS_URL,
                params={
                    "origin": f"{origem[0]},{origem[1]}",
                    "destination": f"{destino[0]},{destino[1]}",
                    "mode": "driving",
                    "region": "br",
                    "language": "pt-BR",
                    "key": api_key,
                },
                timeout=TIMEOUT_S,
            )
        except requests.RequestException:
            resp = None
        if resp is not None and resp.status_code == 200:
            dados = resp.json()
            if dados.get("status") == "OK":
                rotas = dados.get("routes") or []
                encoded = ((rotas[0].get("overview_polyline") or {}).get("points")) if rotas else ""
                coords = decodificar_polyline(encoded or "")
                if len(coords) >= 2:
                    return coords

    from core.ors import ler_api_key

    try:
        ors_key = ler_api_key()
    except ErroExterno:
        ors_key = None
    if not ors_key:
        raise ErroExterno(
            "Não foi possível traçar a via. "
            "Ative a Directions API no Google Cloud ou confira a chave ORS_API_KEY."
        )
    corpo = {"coordinates": [[origem[1], origem[0]], [destino[1], destino[0]]]}
    try:
        resp = requests.post(
            "https://api.openrouteservice.org/v2/directions/driving-car/geojson",
            json=corpo,
            headers={"Authorization": ors_key, "Content-Type": "application/json"},
            timeout=TIMEOUT_S,
        )
    except requests.RequestException as e:
        raise ErroExterno(f"Roteamento falhou na rede: {e}") from e
    if resp.status_code != 200:
        raise ErroExterno(f"OpenRouteService respondeu HTTP {resp.status_code}")
    features = resp.json().get("features") or []
    if not features:
        return []
    geom = features[0].get("geometry") or {}
    return _coords_de_geometria_nominatim(geom) or []


def nucleo_nome_via(nome: str) -> str:
    """Rua Cruz de Malta → Cruz de Malta (para regex OSM)."""
    texto = expandir_abrev_via(nome).strip()
    return re.sub(
        r"^(rua|avenida|alameda|travessa|praca|praça|rodovia)\s+",
        "",
        texto,
        flags=re.IGNORECASE,
    ).strip() or texto


def bbox_pinos(
    origem: tuple[float, float],
    destino: tuple[float, float],
    *,
    pad: float = 0.003,
) -> tuple[float, float, float, float]:
    """south, west, north, east."""
    lats = [origem[0], destino[0]]
    lons = [origem[1], destino[1]]
    return min(lats) - pad, min(lons) - pad, max(lats) + pad, max(lons) + pad


def montar_consulta_bbox(nome: str, south: float, west: float, north: float, east: float) -> str:
    nucleo = nucleo_nome_via(nome).replace('"', '\\"')
    return (
        f"[out:json][timeout:{TIMEOUT_OVERPASS_S}];\n"
        f'way["highway"]["name"~"{nucleo}",i]({south},{west},{north},{east});\n'
        f"out geom;\n"
    )


def fundir_ways(resposta: dict):
    from shapely.ops import linemerge, unary_union

    linhas = []
    for el in resposta.get("elements") or []:
        if el.get("type") != "way":
            continue
        geom = el.get("geometry") or []
        if len(geom) < 2:
            continue
        linhas.append(LineString([(p["lon"], p["lat"]) for p in geom]))
    if not linhas:
        return None
    if len(linhas) == 1:
        return linhas[0]
    return linemerge(unary_union(linhas))


def recortar_linha_entre_pinos(
    linha,
    origem: tuple[float, float],
    destino: tuple[float, float],
):
    """Recorta o eixo da via entre dois pinos (lat, lon)."""
    from shapely.geometry import Point
    from shapely.ops import substring

    if linha is None or linha.is_empty:
        return None
    p1 = Point(origem[1], origem[0])
    p2 = Point(destino[1], destino[0])
    if linha.geom_type == "MultiLineString":
        linha = min(linha.geoms, key=lambda g: g.distance(p1) + g.distance(p2))
    if linha.geom_type != "LineString" or linha.length == 0:
        return None
    f1 = linha.project(p1, normalized=True)
    f2 = linha.project(p2, normalized=True)
    if abs(f1 - f2) < 1e-5:
        return None
    if f1 > f2:
        f1, f2 = f2, f1
    recorte = substring(linha, f1, f2, normalized=True)
    if recorte is None or recorte.is_empty or recorte.geom_type != "LineString":
        return None
    if len(recorte.coords) < 2:
        return None
    return recorte


def eixo_osm_entre_pinos(
    nome: str,
    origem: tuple[float, float],
    destino: tuple[float, float],
    sessao: requests.Session | None = None,
):
    """Eixo OSM da via no retângulo dos dois pinos, recortado entre eles."""
    sessao = sessao or requests.Session()
    south, west, north, east = bbox_pinos(origem, destino)
    consulta = montar_consulta_bbox(nome, south, west, north, east)
    resposta = consultar_overpass(sessao, consulta)
    fundida = fundir_ways(resposta)
    return recortar_linha_entre_pinos(fundida, origem, destino)


def eixo_snap_roads(
    origem: tuple[float, float],
    destino: tuple[float, float],
    api_key: str,
    *,
    amostras: int = 20,
) -> list[tuple[float, float]]:
    """Interpola a reta entre os pinos e cola no asfalto (Google Roads)."""
    if amostras < 2:
        amostras = 2
    path = []
    for i in range(amostras):
        t = i / (amostras - 1)
        lat = origem[0] + t * (destino[0] - origem[0])
        lon = origem[1] + t * (destino[1] - origem[1])
        path.append(f"{lat},{lon}")
    try:
        resp = requests.get(
            "https://roads.googleapis.com/v1/snapToRoads",
            params={"path": "|".join(path), "interpolate": "true", "key": api_key},
            timeout=TIMEOUT_S,
        )
    except requests.RequestException:
        return []
    if resp.status_code != 200:
        return []
    snapped = (resp.json() or {}).get("snappedPoints") or []
    coords = []
    for p in snapped:
        loc = p.get("location") or {}
        if loc.get("latitude") is None or loc.get("longitude") is None:
            continue
        coords.append((float(loc["longitude"]), float(loc["latitude"])))
    return coords if len(coords) >= 2 else []


def coords_eixo_entre_pinos(
    nome: str,
    origem: tuple[float, float],
    destino: tuple[float, float],
    api_key: str | None = None,
) -> tuple[list[tuple[float, float]], str]:
    """
    Eixo da via entre dois pinos — não é rota de carro.

    1. OSM (nome da rua no retângulo dos pinos)
    2. Google Roads (cola a reta no asfalto)
    3. Reta entre os pinos
    """
    try:
        recorte = eixo_osm_entre_pinos(nome, origem, destino)
        if recorte is not None:
            return list(recorte.coords), "osm-eixo"
    except (OverpassIndisponivel, ErroExterno, requests.RequestException):
        pass

    if api_key:
        snapped = eixo_snap_roads(origem, destino, api_key)
        if snapped:
            return snapped, "google-roads"

    return [(origem[1], origem[0]), (destino[1], destino[0])], "eixo-reto"


def buscar_features_google_rota(
    nome: str,
    trecho: RegistroTrecho | None = None,
    tipo: str | None = None,
    entrada: str | None = None,
) -> list[dict]:
    """Traçado da via via Google Geocoding + Directions (funciona no Streamlit Cloud)."""
    from core.google_geo import ler_google_api_key

    api_key = ler_google_api_key()
    if not api_key:
        return []

    extremos = _pontos_google_para_rota(api_key, nome, trecho, entrada=entrada)
    if not extremos:
        return []
    try:
        coords = directions_entre_pontos(extremos[0], extremos[1], api_key)
    except ErroExterno:
        return []
    tipo_via = _normalizar_tipo(tipo) or "rua"
    feature = feature_de_linha(coords, nome, origem="google-directions", tipo=tipo_via)
    return [feature] if feature else []


def buscar_barreira_entre_pontos(
    nome: str,
    origem: tuple[float, float],
    destino: tuple[float, float],
    *,
    tipo: str | None = None,
    numero_inicio: int | None = None,
    numero_fim: int | None = None,
    paridade: str | None = None,
) -> list[Barreira]:
    """Traça a barreira pelo eixo da via entre dois pinos — não é rota de carro."""
    from core.google_geo import ler_google_api_key

    nome = expandir_abrev_via(nome_via_de_entrada(nome) or nome)
    if not nome:
        raise ErroExterno("Informe o nome da rua para o trecho desenhado.")
    api_key = ler_google_api_key()
    coords, origem_geom = coords_eixo_entre_pinos(nome, origem, destino, api_key)
    tipo_via = _normalizar_tipo(tipo) or "rua"
    feature = feature_de_linha(coords, nome, origem=origem_geom, tipo=tipo_via)
    if not feature:
        raise ErroExterno("O Google não devolveu um traçado entre os dois pontos.")
    barreiras = _features_para_barreiras([feature])
    for barreira in barreiras:
        if numero_inicio:
            barreira.numero_inicio = numero_inicio
        if numero_fim:
            barreira.numero_fim = numero_fim
        if paridade:
            barreira.paridade = paridade
    return barreiras


def buscar_barreira_entre_links(
    nome: str,
    link_inicio: str,
    link_fim: str,
    *,
    tipo: str | None = None,
    numero_inicio: int | None = None,
    numero_fim: int | None = None,
    paridade: str | None = None,
) -> list[Barreira]:
    """Traça a barreira pelo caminho entre dois pins de links do Google Maps."""
    from core.google_geo import endereco_de_link_maps, pin_de_link_maps

    origem = pin_de_link_maps(link_inicio)
    destino = pin_de_link_maps(link_fim)
    if origem == destino:
        raise ErroExterno(
            "Os dois links apontam para o mesmo ponto. "
            "Cole o início e o fim da barreira (extremos da rua)."
        )
    nome_via = (nome or "").strip()
    if not nome_via:
        try:
            nome_via = endereco_de_link_maps(link_inicio)
        except ErroExterno:
            nome_via = ""
    if not nome_via:
        raise ErroExterno("Informe o nome da rua ou use um link que traga o nome do lugar.")
    return buscar_barreira_entre_pontos(
        nome_via,
        origem,
        destino,
        tipo=tipo,
        numero_inicio=numero_inicio,
        numero_fim=numero_fim,
        paridade=paridade,
    )


def barreira_em_sao_paulo(barreira: Barreira) -> bool:
    from core.geo_limites import coordenada_em_sao_paulo

    lon, lat = barreira.geometria.centroid.coords[0]
    return coordenada_em_sao_paulo(lat, lon)


def filtrar_barreiras_em_sao_paulo(barreiras: list[Barreira]) -> list[Barreira]:
    return [b for b in barreiras if barreira_em_sao_paulo(b)]


def filtrar_barreiras_perto(
    barreiras: list[Barreira],
    lat: float,
    lon: float,
    *,
    raio_m: float = 2500,
) -> list[Barreira]:
    """Mantém só trechos cujo centro está a até ``raio_m`` do pino de referência."""
    from shapely.geometry import Point

    from core.geo import crs_utm_local, para_metrico

    crs = crs_utm_local(lon, lat)
    centro = para_metrico(Point(lon, lat), crs)
    perto: list[Barreira] = []
    for barreira in barreiras:
        dist = para_metrico(barreira.geometria.centroid, crs).distance(centro)
        if dist <= raio_m:
            perto.append(barreira)
    return perto


def refinar_preview(
    barreiras: list[Barreira],
    entrada: str | None = None,
    *,
    ancora: tuple[float, float] | None = None,
) -> tuple[list[Barreira], int]:
    """
    Descarta trechos fora da capital e, se houver pino de referência,
    os que estão longe (homônimas em outras cidades).
    """
    na_capital = filtrar_barreiras_em_sao_paulo(barreiras)
    if ancora is None and entrada:
        ancora = ancora_da_entrada(entrada)
    if ancora and len(na_capital) > 1:
        lat, lon = ancora
        perto = filtrar_barreiras_perto(na_capital, lat, lon)
        if perto:
            na_capital = perto
    removidos = len(barreiras) - len(na_capital)
    return na_capital, removidos


def ancora_da_entrada(entrada: str) -> tuple[float, float] | None:
    """Pino de referência (lat, lon) a partir de link ou endereço — para filtrar homônimas."""
    from core.google_geo import (
        geocode_ponto,
        ler_google_api_key,
        parece_link_maps,
        pin_de_link_maps,
    )

    texto = (entrada or "").strip()
    if not texto:
        return None
    if parece_link_maps(texto):
        try:
            return pin_de_link_maps(texto)
        except ErroExterno:
            return None
    api_key = ler_google_api_key()
    if not api_key:
        return None
    consulta = texto if "são paulo" in texto.lower() or "sao paulo" in texto.lower() else f"{texto}, São Paulo, SP"
    return geocode_ponto(consulta, api_key)


def comprimento_m(barreira: Barreira) -> float:
    """Comprimento da geometria em metros (UTM local)."""
    from core.geo import crs_utm_local, para_metrico

    lon, lat = barreira.geometria.centroid.coords[0]
    return float(para_metrico(barreira.geometria, crs_utm_local(lon, lat)).length)


def aplicar_metadados(
    barreiras: list[Barreira],
    *,
    nome: str | None = None,
    tipo: str | None = None,
    numero_inicio: int | None = None,
    numero_fim: int | None = None,
    paridade: str | None = None,
) -> list[Barreira]:
    """Ajusta rótulo/tipo/faixa sem recalcular a geometria."""
    tipo_fixo = _normalizar_tipo(tipo)
    nome_limpo = expandir_abrev_via((nome or "").strip()) if nome else ""
    for barreira in barreiras:
        if nome_limpo:
            barreira.nome = nome_limpo
        if tipo_fixo:
            barreira.tipo = tipo_fixo
        barreira.numero_inicio = numero_inicio if numero_inicio else None
        barreira.numero_fim = numero_fim if numero_fim else None
        barreira.paridade = paridade if paridade and paridade != "ambos" else None
    return barreiras


def _features_fallback(
    sessao: requests.Session,
    nome: str,
    trecho: RegistroTrecho,
    tipo: str | None,
    entrada: str | None = None,
) -> list[dict]:
    """Nominatim e Google — usados quando Overpass falha ou não acha a via."""
    try:
        features = buscar_features_nominatim(sessao, nome, trecho)
    except (ErroExterno, Exception):
        features = []
    if features:
        return features
    return buscar_features_google_rota(nome, trecho, tipo, entrada=entrada)


def _features_para_barreiras(features: list[dict]) -> list[Barreira]:
    barreiras: list[Barreira] = []
    for i, feature in enumerate(features):
        barreira = barreira_de_feature(feature, i)
        if barreira:
            barreiras.append(barreira)
    return barreiras


def _normalizar_tipo(tipo: str | None) -> str | None:
    if not tipo or tipo == "(detectar automaticamente)":
        return None
    if tipo in TIPOS_BARREIRA:
        return tipo
    return None


def buscar_barreiras_rua(
    entrada: str,
    *,
    numero_inicio: int | None = None,
    numero_fim: int | None = None,
    paridade: str | None = None,
    tipo: str | None = None,
    relacao_id: int = RELACAO_SP_PADRAO,
    regex: bool = False,
) -> list[Barreira]:
    """
    Busca trechos de barreira no OSM a partir de nome/endereço de rua.

    Sem números de início/fim, importa todos os ways da via em São Paulo.
    Com faixa numérica, recorta cada trecho OSM quando houver ``addr:housenumber``.
    """
    from core.google_geo import endereco_de_link_maps, parece_link_maps

    if parece_link_maps(entrada):
        entrada = endereco_de_link_maps(entrada)

    nome = nome_via_de_entrada(entrada)
    if not nome:
        raise ErroExterno("Informe o nome, o endereço ou o link do Google Maps da rua.")

    trecho = RegistroTrecho(
        nome,
        numero_inicio if numero_inicio and numero_inicio > 0 else None,
        numero_fim if numero_fim and numero_fim > 0 else None,
        paridade if paridade else None,
    )

    sessao = requests.Session()
    features: list[dict] = []

    # Google primeiro: no Streamlit Cloud o Overpass costuma falhar ou não achar
    # o nome abreviado (R. Cruz de Malta vs Rua Cruz de Malta).
    if not regex:
        try:
            features = buscar_features_google_rota(nome, trecho, tipo, entrada=entrada)
        except ErroExterno:
            features = []

    if not features:
        consulta = montar_consulta([nome], relacao_id, regex=regex)
        try:
            resposta = consultar_overpass(sessao, consulta)

            way_ids = [e["id"] for e in resposta.get("elements") or [] if e.get("type") == "way"]
            marcas_por_way: dict[int, list[MarcaNumero]] = {}
            if way_ids and trecho.tem_faixa():
                consulta_nums = montar_consulta_numeros(way_ids)
                if consulta_nums:
                    resp_nums = consultar_overpass(sessao, consulta_nums)
                    marcas_por_way = indexar_numeros_por_way(resposta, resp_nums)

            geojson = overpass_para_geojson(
                resposta, trechos=[trecho], marcas_por_way=marcas_por_way
            )
            features = geojson.get("features") or []
        except OverpassIndisponivel:
            features = _features_fallback(sessao, nome, trecho, tipo, entrada=entrada)

    if not features and not regex:
        return buscar_barreiras_rua(
            nome,
            numero_inicio=numero_inicio,
            numero_fim=numero_fim,
            paridade=paridade,
            tipo=tipo,
            relacao_id=relacao_id,
            regex=True,
        )

    if not features:
        try:
            features = _features_fallback(sessao, nome, trecho, tipo, entrada=entrada)
        except ErroExterno:
            features = []

    if not features:
        dica = (
            f"Nenhum trecho encontrado para {nome!r}. "
            "Tente só o nome da via (ex.: Rua Cruz de Malta) "
            "ou marque o início e o fim no mapa."
        )
        raise ErroExterno(dica)

    tipo_fixo = _normalizar_tipo(tipo)
    barreiras = _features_para_barreiras(features)
    for barreira in barreiras:
        if tipo_fixo:
            barreira.tipo = tipo_fixo
        if trecho.numero_inicio:
            barreira.numero_inicio = trecho.numero_inicio
        if trecho.numero_fim:
            barreira.numero_fim = trecho.numero_fim
        if trecho.paridade:
            barreira.paridade = trecho.paridade
    barreiras, _ = refinar_preview(barreiras, entrada)
    if not barreiras:
        raise ErroExterno(
            f"Os trechos de {nome!r} ficaram fora de São Paulo capital. "
            "Use os dois links (início e fim) da rua na capital."
        )
    return barreiras
