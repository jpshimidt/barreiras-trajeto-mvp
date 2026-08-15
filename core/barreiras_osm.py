"""Busca de geometria de barreiras no OpenStreetMap (Overpass)."""

from __future__ import annotations

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
OVERPASS = "https://overpass-api.de/api/interpreter"
USER_AGENT = "barreiras-trajeto-mvp/0.1 (cadastro de barreiras)"

# Relação OSM de São Paulo capital (admin_level=8) — constante documentada no README.
RELACAO_SP_PADRAO = 298285

TIMEOUT_CONSULTA_S = 180
TIMEOUT_OVERPASS_S = 120
TENTATIVAS = 4

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


def nome_via_de_entrada(texto: str) -> str:
    """Extrai logradouro de endereço colado ou devolve o texto como nome de rua."""
    texto = texto.strip()
    if not texto:
        return ""
    endereco = parse_endereco_maps(texto)
    return (endereco.logradouro or texto).strip()


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
    espera = 5
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            resp = sessao.post(
                OVERPASS,
                data={"data": consulta},
                timeout=TIMEOUT_CONSULTA_S,
                headers={"User-Agent": USER_AGENT},
            )
        except requests.RequestException as e:
            raise ErroExterno(f"Overpass falhou na rede: {e}") from e
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code in (429, 504) and tentativa < TENTATIVAS:
            time.sleep(espera)
            espera *= 2
            continue
        raise ErroExterno(f"Overpass respondeu HTTP {resp.status_code}: {resp.text[:300]}")
    raise ErroExterno("Overpass não respondeu depois de várias tentativas.")


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
    nome = nome_via_de_entrada(entrada)
    if not nome:
        raise ErroExterno("Informe o nome ou endereço da rua.")

    trecho = RegistroTrecho(
        nome,
        numero_inicio if numero_inicio and numero_inicio > 0 else None,
        numero_fim if numero_fim and numero_fim > 0 else None,
        paridade if paridade else None,
    )

    sessao = requests.Session()
    consulta = montar_consulta([nome], relacao_id, regex=regex)
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
        dica = (
            f"Nenhum trecho encontrado para {nome!r} no OpenStreetMap. "
            "Confira a grafia (ex.: como aparece no Google Maps) ou tente só o nome da via."
        )
        if trecho.tem_faixa():
            dica += " Com faixa de número, o OSM precisa ter portas cadastradas na rua."
        raise ErroExterno(dica)

    tipo_fixo = _normalizar_tipo(tipo)
    barreiras = _features_para_barreiras(features)
    if tipo_fixo:
        for barreira in barreiras:
            barreira.tipo = tipo_fixo
    return barreiras
