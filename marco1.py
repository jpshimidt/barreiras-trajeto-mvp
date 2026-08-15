#!/usr/bin/env python3
"""
Núcleo em linha de comando do app de elegibilidade a transporte escolar.

Endereços fixos no código, barreiras num GeoJSON local, decisão impressa no
terminal. A lógica mora em `core/`; aqui só ficam os casos fixos e a saída.

Uso:
    export ORS_API_KEY="..."
    python marco1.py                     # roda o caso 1
    python marco1.py --caso 2
    python marco1.py --todos
    python marco1.py --todos --offline   # sem API: valida só a geometria
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from core.barreiras import BUFFER_M_PADRAO, Barreira, barreiras_atingidas, carregar_barreiras
from core.decisao import decidir
from core.erros import ErroExterno
from core.geocode import Local, candidatos_ambiguos, geocodificar, montar_consulta
from core.ors import ler_api_key
from core.routing import Rota, rota_a_pe, rota_reta

ARQUIVO_BARREIRAS = Path(__file__).parent / "dados" / "barreiras.geojson"


@dataclass
class Caso:
    """Um caso fixo: os dois endereços e a flag da tabela de decisão."""

    descricao: str
    endereco_casa: str
    cep_casa: str
    endereco_escola: str
    cep_escola: str
    escolheu_escola: bool
    esperado: str
    # Usadas SÓ no modo --offline, para exercitar a geometria sem API.
    coords_casa: tuple[float, float]  # (lon, lat)
    coords_escola: tuple[float, float]


CASOS: dict[str, Caso] = {
    "1": Caso(
        descricao="Santana -> Bom Retiro: a rota precisa atravessar a Marginal Tietê",
        endereco_casa="Rua Voluntários da Pátria, 1000, Santana, São Paulo, SP",
        cep_casa="02011-000",
        endereco_escola="Avenida Rudge, 700, Bom Retiro, São Paulo, SP",
        cep_escola="01133-000",
        escolheu_escola=False,
        esperado="COM DIREITO",
        coords_casa=(-46.6280, -23.5100),
        coords_escola=(-46.6440, -23.5265),
    ),
    "2": Caso(
        descricao="Santana -> Santana: percurso curto dentro do mesmo distrito",
        endereco_casa="Rua Voluntários da Pátria, 1000, Santana, São Paulo, SP",
        cep_casa="02011-000",
        endereco_escola="Rua Alfredo Pujol, 500, Santana, São Paulo, SP",
        cep_escola="02017-010",
        escolheu_escola=False,
        esperado="SEM DIREITO",
        coords_casa=(-46.6280, -23.5100),
        coords_escola=(-46.6260, -23.4995),
    ),
    "3": Caso(
        descricao="Mesmo trajeto do caso 1, mas a responsável escolheu a escola",
        endereco_casa="Rua Voluntários da Pátria, 1000, Santana, São Paulo, SP",
        cep_casa="02011-000",
        endereco_escola="Avenida Rudge, 700, Bom Retiro, São Paulo, SP",
        cep_escola="01133-000",
        escolheu_escola=True,
        esperado="SEM DIREITO",
        coords_casa=(-46.6280, -23.5100),
        coords_escola=(-46.6440, -23.5265),
    ),
}


def local_offline(texto: str, cep: str, coords: tuple[float, float]) -> Local:
    lon, lat = coords
    return Local(
        texto_original=montar_consulta(texto, cep),
        endereco_formatado=f"[OFFLINE] {texto}",
        lat=lat,
        lon=lon,
        confianca=None,
    )


def mostrar_local(rotulo: str, candidatos: list[Local]) -> Local:
    """
    Imprime o endereço formatado — a proteção mais eficaz contra erro de
    geocodificação. Havendo empate de score, mostra a lista em vez de escolher
    em silêncio.
    """
    escolhido = candidatos[0]
    print(f"  {rotulo}")
    print(f"    texto enviado ...: {escolhido.texto_original}")
    print(f"    endereço achado .: {escolhido.endereco_formatado}")
    print(f"    coordenada ......: {escolhido.lat:.6f}, {escolhido.lon:.6f}")
    if escolhido.confianca is not None:
        print(f"    confiança .......: {escolhido.confianca:.2f}")

    ambiguos = candidatos_ambiguos(candidatos)
    if ambiguos:
        print("    !! AMBÍGUO — outros candidatos com score próximo:")
        for c in ambiguos:
            print(f"       - {c.endereco_formatado} (confiança {c.confianca:.2f})")
        print("       Confira o CEP antes de confiar na decisão.")
    return escolhido


def resolver_pontos(caso: Caso, offline: bool) -> tuple[Local, Local, Rota]:
    if offline:
        casa = local_offline(caso.endereco_casa, caso.cep_casa, caso.coords_casa)
        escola = local_offline(caso.endereco_escola, caso.cep_escola, caso.coords_escola)
        mostrar_local("CASA", [casa])
        mostrar_local("ESCOLA", [escola])
        print("\n  MODO OFFLINE: rota é uma linha reta, não o menor caminho a pé.")
        print("  Valida projeção/buffer/interseção — não vale como decisão real.")
        return casa, escola, rota_reta(casa, escola)

    api_key = ler_api_key()
    casa = mostrar_local("CASA", geocodificar(caso.endereco_casa, api_key, caso.cep_casa))
    escola = mostrar_local("ESCOLA", geocodificar(caso.endereco_escola, api_key, caso.cep_escola))
    return casa, escola, rota_a_pe(casa, escola, api_key)


def rodar_caso(
    nome: str, caso: Caso, barreiras: list[Barreira], buffer_m: float, offline: bool
) -> bool:
    print("=" * 78)
    print(f"CASO {nome} — {caso.descricao}")
    print("=" * 78)

    _, _, rota = resolver_pontos(caso, offline)
    atingidas = barreiras_atingidas(rota, barreiras, buffer_m)
    resultado = decidir(rota, atingidas, caso.escolheu_escola)

    print()
    print(f"  Escolheu a escola .: {'sim' if caso.escolheu_escola else 'não'}")
    print(f"  Distância a pé ....: {rota.distancia_m:,.0f} m".replace(",", "."))
    print(f"  Buffer da barreira : {buffer_m:.0f} m")
    if atingidas:
        print("  Barreiras tocadas .:")
        for b in atingidas:
            print(f"       - {b.nome} ({b.tipo}) [{b.id}]")
    else:
        print("  Barreiras tocadas .: nenhuma")

    veredito = "COM DIREITO" if resultado.tem_direito else "SEM DIREITO"
    print()
    print(f"  >>> {veredito} <<<")
    print(f"  Motivo: {resultado.motivo}")

    bate = veredito == caso.esperado
    print(f"  Esperado: {caso.esperado} — {'ok' if bate else 'DIVERGIU'}")
    print()
    return bate


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--caso", choices=sorted(CASOS), default="1", help="caso fixo (padrão: 1)")
    parser.add_argument("--todos", action="store_true", help="roda os três casos em sequência")
    parser.add_argument(
        "--buffer", type=float, default=BUFFER_M_PADRAO, help="buffer da barreira em metros (padrão: 5)"
    )
    parser.add_argument("--geojson", type=Path, default=ARQUIVO_BARREIRAS, help="arquivo de barreiras")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="não chama o OpenRouteService: coordenadas fixas e rota em linha reta",
    )
    args = parser.parse_args()

    try:
        barreiras = carregar_barreiras(args.geojson)
        print(f"\n{len(barreiras)} barreiras carregadas de {args.geojson}:")
        for b in barreiras:
            print(f"  - {b.nome} ({b.tipo})")
        print()

        nomes = sorted(CASOS) if args.todos else [args.caso]
        resultados = [rodar_caso(n, CASOS[n], barreiras, args.buffer, args.offline) for n in nomes]
    except ErroExterno as e:
        print(f"\nERRO: {e}", file=sys.stderr)
        return 2

    if len(resultados) > 1:
        print(f"Resumo: {sum(resultados)}/{len(resultados)} casos bateram com o esperado.")
    return 0 if all(resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
