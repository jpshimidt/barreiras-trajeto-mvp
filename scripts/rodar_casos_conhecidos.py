#!/usr/bin/env python3
"""
Roda os casos de `testes/casos_conhecidos.csv` contra o pipeline real e compara
com a resposta que já se sabe correta.

    export ORS_API_KEY="..."
    python scripts/rodar_casos_conhecidos.py
    python scripts/rodar_casos_conhecidos.py --buffer 10

Chama a API de verdade (2 geocodificações + 1 rota por caso), ao contrário da
suíte do pytest. Imprime tudo no terminal e **não grava nada**: o arquivo de
entrada tem endereços residenciais de crianças.

Se houver divergência, investigue caso a caso ANTES de mexer no buffer. A causa
costuma ser geocodificação errada ou barreira faltando no cadastro.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Rodando como `python scripts/...`, o sys.path começa em scripts/ e não enxerga core/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.barreiras import BUFFER_M_PADRAO, barreiras_atingidas, carregar_barreiras  # noqa: E402
from core.decisao import decidir  # noqa: E402
from core.erros import ErroExterno  # noqa: E402
from core.geocode import geocodificar  # noqa: E402
from core.ors import ler_api_key  # noqa: E402
from core.routing import rota_a_pe  # noqa: E402

COLUNAS = [
    "id",
    "endereco_casa",
    "cep_casa",
    "endereco_escola",
    "cep_escola",
    "escolheu_escola",
    "resultado_esperado",
]

SIM = {"sim", "s", "true", "1"}
NAO = {"nao", "não", "n", "false", "0", ""}

COM_DIREITO = {"com_direito", "com direito", "sim", "true"}
SEM_DIREITO = {"sem_direito", "sem direito", "nao", "não", "false"}


@dataclass
class CasoConhecido:
    id: str
    endereco_casa: str
    cep_casa: str
    endereco_escola: str
    cep_escola: str
    escolheu_escola: bool
    esperado_tem_direito: bool


def sim_ou_nao(valor: str, campo: str, linha: int) -> bool:
    v = (valor or "").strip().lower()
    if v in SIM:
        return True
    if v in NAO:
        return False
    raise ValueError(f"linha {linha}: {campo}={valor!r} — use 'sim' ou 'nao'")


def esperado_para_bool(valor: str, linha: int) -> bool:
    v = (valor or "").strip().lower()
    if v in COM_DIREITO:
        return True
    if v in SEM_DIREITO:
        return False
    raise ValueError(
        f"linha {linha}: resultado_esperado={valor!r} — use 'com_direito' ou 'sem_direito'"
    )


def ler_casos(caminho: Path) -> list[CasoConhecido]:
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        leitor = csv.DictReader(f)
        faltando = [c for c in COLUNAS if c not in (leitor.fieldnames or [])]
        if faltando:
            raise ValueError(f"{caminho}: faltam as colunas {', '.join(faltando)}")

        casos = []
        for linha, registro in enumerate(leitor, start=2):
            if not (registro.get("id") or "").strip():
                continue  # linha em branco
            casos.append(
                CasoConhecido(
                    id=registro["id"].strip(),
                    endereco_casa=registro["endereco_casa"].strip(),
                    cep_casa=(registro["cep_casa"] or "").strip(),
                    endereco_escola=registro["endereco_escola"].strip(),
                    cep_escola=(registro["cep_escola"] or "").strip(),
                    escolheu_escola=sim_ou_nao(registro["escolheu_escola"], "escolheu_escola", linha),
                    esperado_tem_direito=esperado_para_bool(registro["resultado_esperado"], linha),
                )
            )
    return casos


def rotulo(tem_direito: bool) -> str:
    return "COM DIREITO" if tem_direito else "SEM DIREITO"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", type=Path, default=Path("testes/casos_conhecidos.csv"))
    parser.add_argument("--geojson", type=Path, default=Path("dados/barreiras.geojson"))
    parser.add_argument("--buffer", type=float, default=BUFFER_M_PADRAO)
    parser.add_argument(
        "--pausa", type=float, default=1.0, help="segundos entre casos, para não pesar na API"
    )
    args = parser.parse_args()

    try:
        casos = ler_casos(args.csv)
    except (OSError, ValueError) as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 2

    if not casos:
        print(
            f"{args.csv} está vazio.\n\n"
            "Monte de 15 a 20 casos da Zona Norte cuja resposta correta já se saiba,\n"
            "metade com direito e metade sem. Caso cuja resposta ninguém consegue\n"
            "conferir não valida nada.\n\n"
            "  id,endereco_casa,cep_casa,endereco_escola,cep_escola,escolheu_escola,resultado_esperado\n"
            '  01,"R. X, 100, Bairro Y",01234-567,"EM Fulano, R. Z, 50",04321-000,nao,com_direito',
            file=sys.stderr,
        )
        return 2

    try:
        barreiras = carregar_barreiras(args.geojson)
        api_key = ler_api_key()
    except ErroExterno as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 2

    print(f"{len(casos)} casos | buffer {args.buffer:.0f} m | {len(barreiras)} trechos de barreira\n")

    acertos, divergencias, falhas = 0, [], []

    for caso in casos:
        print(f"[{caso.id}] {caso.endereco_casa}  ->  {caso.endereco_escola}")
        try:
            if caso.escolheu_escola:
                resultado = decidir(None, [], escolheu_escola=True)
            else:
                casa = geocodificar(caso.endereco_casa, api_key, caso.cep_casa)[0]
                escola = geocodificar(caso.endereco_escola, api_key, caso.cep_escola)[0]
                print(f"      casa   -> {casa.endereco_formatado}")
                print(f"      escola -> {escola.endereco_formatado}")
                rota = rota_a_pe(casa, escola, api_key)
                atingidas = barreiras_atingidas(rota, barreiras, args.buffer)
                resultado = decidir(rota, atingidas, escolheu_escola=False)
        except ErroExterno as e:
            print(f"      FALHOU: {e}\n", file=sys.stderr)
            falhas.append(caso.id)
            continue

        obtido = rotulo(resultado.tem_direito)
        esperado = rotulo(caso.esperado_tem_direito)
        if resultado.tem_direito == caso.esperado_tem_direito:
            acertos += 1
            print(f"      ok — {obtido}")
        else:
            divergencias.append(caso.id)
            print(f"      DIVERGIU — esperado {esperado}, obtido {obtido}")
        print(f"      {resultado.motivo}")
        if resultado.distancia_m is not None:
            print(f"      distância: {resultado.distancia_m:,.0f} m".replace(",", "."))
        print()

        if args.pausa:
            time.sleep(args.pausa)

    print("=" * 70)
    print(f"{acertos}/{len(casos)} casos bateram com o esperado.")
    if falhas:
        print(f"Falharam por erro externo: {', '.join(falhas)}")
    if divergencias:
        print(f"Divergiram: {', '.join(divergencias)}")
        print(
            "\nAntes de mexer no buffer, investigue cada divergência:\n"
            "  1. o endereço formatado acima é mesmo o endereço certo?\n"
            "  2. a rua-barreira do caso está no cadastro, com a grafia do OSM?\n"
            "A causa quase nunca é o buffer."
        )
    return 0 if not divergencias and not falhas else 1


if __name__ == "__main__":
    sys.exit(main())
