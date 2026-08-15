#!/usr/bin/env python3
"""
Converte uma lista de trechos de barreira no GeoJSON, via Overpass API.

Cada linha do arquivo de entrada pode ser:
  - ``Marginal Tietê`` — rua inteira
  - ``Av. X;100;500`` — só do nº 100 ao 500 (geometria recortada com OSM)
  - ``Av. X;100;500;par`` — intervalo com paridade

Roda OFFLINE, quando o cadastro muda — nunca no runtime do app.

    python scripts/importar_barreiras.py --ruas-teste --dry-run
    python scripts/importar_barreiras.py --ruas-teste
    python scripts/importar_barreiras.py --ruas minhas_ruas.txt --saida dados/barreiras.geojson
    python scripts/importar_barreiras.py --ruas minhas_ruas.txt --regex

Depois de importar, a validação visual é OBRIGATÓRIA: abra o GeoJSON no geojson.io
e confira se as linhas caíram onde deveriam. Uma barreira que não foi importada gera
silenciosamente um "sem direito" errado, e ninguém vai perceber.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from datetime import date
from pathlib import Path

import requests

from core.recorte_trecho import (
    MarcaNumero,
    RegistroTrecho,
    marcas_de_coordenadas,
    parse_linha_trecho,
    recortar_linha_por_numeros,
)

MUNICIPIO = "São Paulo"

NOMINATIM = "https://nominatim.openstreetmap.org/search"
OVERPASS = "https://overpass-api.de/api/interpreter"
USER_AGENT = "barreiras-trajeto-mvp/0.1 (importador de barreiras)"

TIMEOUT_CONSULTA_S = 180  # São Paulo é área grande; a consulta demora
TIMEOUT_OVERPASS_S = 120  # o [timeout:] de dentro da própria consulta
TENTATIVAS = 4

# Trechos de teste — maioria da Zona Norte; inclui exemplo com faixa de número.
TRECHOS_TESTE = [
    RegistroTrecho("Marginal Tietê"),
    RegistroTrecho("Avenida Engenheiro Caetano Álvares"),
    RegistroTrecho("Avenida Inajar de Souza", 100, 2500),
    RegistroTrecho("Avenida Santos Dumont"),
    RegistroTrecho("Avenida Cruzeiro do Sul"),
    RegistroTrecho("Rodovia Fernão Dias"),
]

# `highway` do OSM -> rótulo que o usuário final lê no motivo da decisão.
TIPOS = {
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


# --------------------------------------------------------------------------- #
# Consulta
# --------------------------------------------------------------------------- #


def area_id(relacao_id: int) -> int:
    """Área do Overpass a partir do ID da relação OSM."""
    return 3600000000 + relacao_id


def montar_consulta(ruas: list[str], relacao_id: int, regex: bool = False) -> str:
    """
    Monta a consulta Overpass.

    Dois detalhes que não são opcionais:

    - o filtro ["highway"] — sem ele a consulta casa qualquer way com aquele nome:
      trilhos, cursos d'água, limites administrativos. As barreiras são ruas;
    - `out geom;` — devolve as coordenadas inline, sem segunda consulta para os nós.

    Não se filtra por area["name"="São Paulo"]: existe o estado, o município e outras
    localidades homônimas, e a consulta pegaria a área errada. Usa-se o ID da relação.
    """
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


# --------------------------------------------------------------------------- #
# Conversão Overpass -> GeoJSON
# --------------------------------------------------------------------------- #


def slug(texto: str) -> str:
    """'Avenida Inajar de Souza' -> 'avenida-inajar-de-souza'."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", sem_acento.lower()).strip("-")


def feature_de_way(
    elemento: dict,
    importado_em: str,
    trecho: RegistroTrecho | None = None,
    marcas: list[MarcaNumero] | None = None,
) -> dict | None:
    """Um way do Overpass (com `out geom`) vira uma Feature de LineString."""
    from shapely.geometry import LineString

    geometria = elemento.get("geometry") or []
    if len(geometria) < 2:
        return None  # way sem geometria utilizável

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
        "tipo": TIPOS.get(tags.get("highway"), tags.get("highway") or "(sem tipo)"),
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
    """Converte resposta Overpass em FeatureCollection, opcionalmente por trecho."""
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
    """Associa nós com addr:housenumber aos ways e projeta sobre a geometria."""
    from shapely.geometry import LineString

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
    """
    Nomes pedidos que não voltaram nenhum way.

    Grafia no OSM varia muito ("Marginal Tietê", "Marginal Tiete", "Via Marginal do
    Rio Tietê"). Com `--regex` o nome pedido é substring do nome devolvido, então a
    comparação é por substring nos dois sentidos.
    """
    achados = [f["properties"]["nome"].lower() for f in geojson["features"]]
    faltando = []
    for rua in pedidas:
        alvo = rua.lower()
        if not any(alvo in achado or achado in alvo for achado in achados):
            faltando.append(rua)
    return faltando


# --------------------------------------------------------------------------- #
# Rede
# --------------------------------------------------------------------------- #


def descobrir_relacao_sp(sessao: requests.Session) -> int:
    """
    ID da relação OSM do município de São Paulo, via Nominatim.

    Confere que o resultado é `relation` com admin_level 8 (município) — sem isso
    corre-se o risco de pegar o estado, que tem o mesmo nome.
    """
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
    )
    resp.raise_for_status()

    for r in resp.json():
        if r.get("osm_type") != "relation":
            continue
        if str((r.get("extratags") or {}).get("admin_level")) != "8":
            continue
        return int(r["osm_id"])

    raise SystemExit(
        "Nominatim não devolveu a relação admin_level=8 de São Paulo.\n"
        "Descubra o ID à mão em openstreetmap.org e passe com --relacao-id."
    )


def consultar_overpass(sessao: requests.Session, consulta: str) -> dict:
    """POST com backoff em 429/504 — a área é grande e o serviço é compartilhado."""
    espera = 5
    for tentativa in range(1, TENTATIVAS + 1):
        resp = sessao.post(OVERPASS, data={"data": consulta}, timeout=TIMEOUT_CONSULTA_S)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code in (429, 504) and tentativa < TENTATIVAS:
            print(
                f"  Overpass respondeu {resp.status_code}; nova tentativa em {espera}s "
                f"({tentativa}/{TENTATIVAS - 1})",
                file=sys.stderr,
            )
            time.sleep(espera)
            espera *= 2
            continue
        raise SystemExit(f"Overpass respondeu HTTP {resp.status_code}: {resp.text[:300]}")
    raise SystemExit("Overpass não respondeu depois de várias tentativas.")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def ler_trechos(caminho: Path) -> list[RegistroTrecho]:
    """Lê trechos do cadastro (rua inteira ou faixa de número)."""
    trechos: list[RegistroTrecho] = []
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        trecho = parse_linha_trecho(linha)
        if trecho:
            trechos.append(trecho)
    return trechos


def nomes_unicos(trechos: list[RegistroTrecho]) -> list[str]:
    vistos: list[str] = []
    for trecho in trechos:
        if trecho.nome not in vistos:
            vistos.append(trecho.nome)
    return vistos


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    fonte = parser.add_mutually_exclusive_group(required=True)
    fonte.add_argument("--ruas", type=Path, help="arquivo com uma rua por linha")
    fonte.add_argument(
        "--ruas-teste", action="store_true", help="usa a lista de teste embutida (Zona Norte)"
    )
    parser.add_argument(
        "--saida", type=Path, default=Path("dados/barreiras.geojson"), help="GeoJSON de saída"
    )
    parser.add_argument(
        "--relacao-id",
        type=int,
        help="ID da relação OSM de São Paulo (descoberto via Nominatim se omitido)",
    )
    parser.add_argument(
        "--regex",
        action="store_true",
        help="busca o nome por regex, sem diferenciar acento/caixa — use quando o nome exato não retornar nada",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="só imprime a consulta, sem chamar a rede"
    )
    args = parser.parse_args()

    trechos = TRECHOS_TESTE if args.ruas_teste else ler_trechos(args.ruas)
    if not trechos:
        raise SystemExit("Lista de trechos vazia.")

    ruas = nomes_unicos(trechos)
    print(f"{len(trechos)} trechos pedidos ({len(ruas)} ruas distintas):")
    for trecho in trechos:
        if trecho.tem_faixa():
            print(
                f"  - {trecho.nome} "
                f"(nº {trecho.numero_inicio or '…'}–{trecho.numero_fim or '…'}"
                f"{', ' + trecho.paridade if trecho.paridade else ''})"
            )
        else:
            print(f"  - {trecho.nome} (rua inteira)")
    print()

    sessao = requests.Session()
    sessao.headers["User-Agent"] = USER_AGENT

    relacao_id = args.relacao_id
    if relacao_id is None:
        if args.dry_run:
            relacao_id = 0  # placeholder só para exibir a consulta
        else:
            print("Descobrindo a relação OSM de São Paulo no Nominatim...")
            relacao_id = descobrir_relacao_sp(sessao)
            print(f"  relação {relacao_id} -> area {area_id(relacao_id)}")
            print("  ANOTE esse número no README: é constante.\n")

    consulta = montar_consulta(ruas, relacao_id, regex=args.regex)

    if args.dry_run:
        print("Consulta Overpass (--dry-run, nada foi enviado):\n")
        print(consulta)
        if args.relacao_id is None:
            print("Rode sem --dry-run ou passe --relacao-id para a área correta.")
        return 0

    print("Consultando o Overpass (pode levar minutos)...")
    resposta = consultar_overpass(sessao, consulta)

    way_ids = [e["id"] for e in resposta.get("elements") or [] if e.get("type") == "way"]
    marcas_por_way: dict[int, list[MarcaNumero]] = {}
    if way_ids and any(t.tem_faixa() for t in trechos):
        print(f"Buscando números de porta em {len(way_ids)} ways...")
        consulta_nums = montar_consulta_numeros(way_ids)
        if consulta_nums:
            resp_nums = consultar_overpass(sessao, consulta_nums)
            marcas_por_way = indexar_numeros_por_way(resposta, resp_nums)
            print(f"  {sum(len(v) for v in marcas_por_way.values())} marcas de número encontradas")

    geojson = overpass_para_geojson(resposta, trechos=trechos, marcas_por_way=marcas_por_way)

    contagem = contar_por_rua(geojson)
    print(f"\n{len(geojson['features'])} ways importados:")
    for nome, quantidade in sorted(contagem.items(), key=lambda x: -x[1]):
        print(f"  {quantidade:>5}  {nome}")

    faltando = ruas_sem_resultado(ruas, geojson)
    if faltando:
        print("\n!! ATENÇÃO — estas ruas não retornaram nenhum way:", file=sys.stderr)
        for rua in faltando:
            print(f"     - {rua}", file=sys.stderr)
        print(
            "   A grafia no OSM provavelmente é outra. Tente de novo com --regex\n"
            "   usando um pedaço distintivo do nome. Barreira que não entra no cadastro\n"
            "   vira 'sem direito' errado, em silêncio.",
            file=sys.stderr,
        )

    suspeitas = [nome for nome, qtd in contagem.items() if qtd <= 2]
    if suspeitas:
        print("\n!! Poucos ways (<=2) — confira se é só um trecho solto:", file=sys.stderr)
        for nome in suspeitas:
            print(f"     - {nome} ({contagem[nome]})", file=sys.stderr)

    if not geojson["features"]:
        raise SystemExit("\nNenhum way importado; o arquivo NÃO foi gravado.")

    args.saida.parent.mkdir(parents=True, exist_ok=True)
    args.saida.write_text(
        json.dumps(geojson, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    tamanho_mb = args.saida.stat().st_size / 1_000_000
    print(f"\nGravado em {args.saida} ({tamanho_mb:.1f} MB)")
    print("Agora abra o arquivo no geojson.io e confira se as linhas caíram onde deveriam.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
