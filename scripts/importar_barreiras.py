#!/usr/bin/env python3
"""
Converte uma lista de nomes de rua no GeoJSON de barreiras, via Overpass API.

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

MUNICIPIO = "São Paulo"

NOMINATIM = "https://nominatim.openstreetmap.org/search"
OVERPASS = "https://overpass-api.de/api/interpreter"
USER_AGENT = "barreiras-trajeto-mvp/0.1 (importador de barreiras)"

TIMEOUT_CONSULTA_S = 180  # São Paulo é área grande; a consulta demora
TIMEOUT_OVERPASS_S = 120  # o [timeout:] de dentro da própria consulta
TENTATIVAS = 4

# Ruas de fronteira da Zona Norte, só para teste enquanto a lista real não chega.
# A grafia aqui é chute: é justamente o que o relatório de ways por rua vai conferir.
RUAS_TESTE = [
    "Marginal Tietê",
    "Avenida Engenheiro Caetano Álvares",
    "Avenida Inajar de Souza",
    "Avenida Santos Dumont",
    "Avenida Cruzeiro do Sul",
    "Rodovia Fernão Dias",
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


def feature_de_way(elemento: dict, importado_em: str) -> dict | None:
    """Um way do Overpass (com `out geom`) vira uma Feature de LineString."""
    geometria = elemento.get("geometry") or []
    if len(geometria) < 2:
        return None  # way sem geometria utilizável

    tags = elemento.get("tags") or {}
    nome = tags.get("name") or "(sem nome)"
    osm_way_id = elemento.get("id")

    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[p["lon"], p["lat"]] for p in geometria],
        },
        "properties": {
            "id": f"{slug(nome)}-{osm_way_id}",
            "nome": nome,
            "tipo": TIPOS.get(tags.get("highway"), tags.get("highway") or "(sem tipo)"),
            "municipio": MUNICIPIO,
            "origem": "overpass",
            "osm_way_id": osm_way_id,
            "importado_em": importado_em,
        },
    }


def overpass_para_geojson(resposta: dict, importado_em: str | None = None) -> dict:
    importado_em = importado_em or date.today().isoformat()
    features = [
        feature
        for elemento in (resposta.get("elements") or [])
        if elemento.get("type") == "way"
        and (feature := feature_de_way(elemento, importado_em)) is not None
    ]
    return {"type": "FeatureCollection", "name": "barreiras", "features": features}


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


def ler_ruas(caminho: Path) -> list[str]:
    """Uma rua por linha; `#` comenta."""
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    ruas = [linha.strip() for linha in linhas]
    return [r for r in ruas if r and not r.startswith("#")]


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

    ruas = RUAS_TESTE if args.ruas_teste else ler_ruas(args.ruas)
    if not ruas:
        raise SystemExit("Lista de ruas vazia.")

    print(f"{len(ruas)} ruas pedidas:")
    for rua in ruas:
        print(f"  - {rua}")
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
    geojson = overpass_para_geojson(resposta)

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
