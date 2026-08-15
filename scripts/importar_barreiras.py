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
import sys
from datetime import date
from pathlib import Path

import requests

from core.barreiras_osm import (
    RELACAO_SP_PADRAO,
    USER_AGENT,
    area_id,
    consultar_overpass,
    contar_por_rua,
    descobrir_relacao_sp,
    montar_consulta,
    montar_consulta_numeros,
    indexar_numeros_por_way,
    overpass_para_geojson,
    ruas_sem_resultado,
)
from core.recorte_trecho import RegistroTrecho, parse_linha_trecho

# Reexportações para testes e scripts legados.
from core.barreiras_osm import feature_de_way, slug  # noqa: F401

TRECHOS_TESTE = [
    RegistroTrecho("Marginal Tietê"),
    RegistroTrecho("Avenida Engenheiro Caetano Álvares"),
    RegistroTrecho("Avenida Inajar de Souza", 100, 2500),
    RegistroTrecho("Avenida Santos Dumont"),
    RegistroTrecho("Avenida Cruzeiro do Sul"),
    RegistroTrecho("Rodovia Fernão Dias"),
]


def ler_trechos(caminho: Path) -> list[RegistroTrecho]:
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
        help="busca o nome por regex, sem diferenciar acento/caixa",
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
            relacao_id = RELACAO_SP_PADRAO
        else:
            print("Descobrindo a relação OSM de São Paulo no Nominatim...")
            relacao_id = descobrir_relacao_sp(sessao)
            print(f"  relação {relacao_id} -> area {area_id(relacao_id)}")
            print("  ANOTE esse número no README: é constante.\n")

    consulta = montar_consulta(ruas, relacao_id, regex=args.regex)

    if args.dry_run:
        print("Consulta Overpass (--dry-run, nada foi enviado):\n")
        print(consulta)
        return 0

    print("Consultando o Overpass (pode levar minutos)...")
    resposta = consultar_overpass(sessao, consulta)

    way_ids = [e["id"] for e in resposta.get("elements") or [] if e.get("type") == "way"]
    marcas_por_way = {}
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
