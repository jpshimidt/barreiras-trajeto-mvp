#!/usr/bin/env python3
"""
Marco 1 — núcleo em linha de comando do app de elegibilidade a transporte escolar.

Script único, endereços fixos no código, barreiras num GeoJSON feito à mão.
Imprime a decisão no terminal. Sem interface, sem persistência.

Regra:
    responsável escolheu a escola  -> SEM DIREITO (não importa o resto)
    rota a pé toca alguma barreira -> COM DIREITO
    caso contrário                 -> SEM DIREITO

Uso:
    export ORS_API_KEY="..."
    python marco1.py                 # roda o caso 1
    python marco1.py --caso 2
    python marco1.py --todos
    python marco1.py --todos --offline   # sem API: valida só a geometria
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import requests
from pyproj import CRS, Transformer
from shapely.geometry import LineString, shape
from shapely.ops import transform as shapely_transform

# --------------------------------------------------------------------------- #
# Configuração
# --------------------------------------------------------------------------- #

MUNICIPIO = "São Paulo"
CENTRO_SP = (-46.6333, -23.5505)  # (lon, lat) — focus.point da geocodificação
BUFFER_M_PADRAO = 5.0

RAIO_PREFILTRO_GRAUS = 0.01  # ~1,1 km: descarta barreiras longe da rota antes de projetar
MARGEM_EMPATE_CONFIANCA = 0.10  # candidatos dentro desta margem = geocodificação ambígua

ARQUIVO_BARREIRAS = Path(__file__).parent / "dados" / "barreiras.geojson"

ORS_GEOCODE = "https://api.openrouteservice.org/geocode/search"
ORS_DIRECTIONS = "https://api.openrouteservice.org/v2/directions/foot-walking/geojson"
TIMEOUT_S = 30


@dataclass
class Caso:
    """Um caso fixo de teste: os dois endereços e a flag da tabela de decisão."""

    descricao: str
    endereco_casa: str
    cep_casa: str
    endereco_escola: str
    cep_escola: str
    escolheu_escola: bool
    esperado: str
    # Coordenadas usadas SÓ no modo --offline, para exercitar a geometria sem API.
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


# --------------------------------------------------------------------------- #
# Contratos
# --------------------------------------------------------------------------- #


@dataclass
class Local:
    texto_original: str
    endereco_formatado: str
    lat: float
    lon: float
    confianca: float | None


@dataclass
class Rota:
    linha: LineString  # EPSG:4326, ordem (lon, lat)
    distancia_m: float
    duracao_s: float


@dataclass
class Barreira:
    id: str
    nome: str
    tipo: str
    geometria: object  # LineString ou MultiLineString em EPSG:4326


@dataclass
class Resultado:
    tem_direito: bool
    motivo: str
    distancia_m: float | None
    barreiras_atingidas: list[str] = field(default_factory=list)


class ErroExterno(RuntimeError):
    """Falha de serviço externo (ORS fora do ar, cota estourada, endereço não achado)."""


# --------------------------------------------------------------------------- #
# Geometria — projeção UTM e buffer métrico
# --------------------------------------------------------------------------- #


def crs_utm_local(lon: float, lat: float) -> CRS:
    """Zona UTM WGS84 do ponto. São Paulo cai na 23S (EPSG:32723)."""
    zona = int((lon + 180) // 6) + 1
    epsg = (32700 if lat < 0 else 32600) + zona
    return CRS.from_epsg(epsg)


def para_metrico(geom, crs_destino: CRS):
    """Projeta de WGS84 (graus) para o CRS métrico. Sem isso, buffer(5) = 5 GRAUS."""
    t = Transformer.from_crs(CRS.from_epsg(4326), crs_destino, always_xy=True)
    return shapely_transform(t.transform, geom)


# --------------------------------------------------------------------------- #
# Barreiras
# --------------------------------------------------------------------------- #


def carregar_barreiras(caminho: Path) -> list[Barreira]:
    with open(caminho, encoding="utf-8") as f:
        colecao = json.load(f)

    barreiras: list[Barreira] = []
    for i, feature in enumerate(colecao.get("features", [])):
        props = feature.get("properties") or {}
        geom = shape(feature["geometry"])
        if geom.is_empty:
            continue
        barreiras.append(
            Barreira(
                id=props.get("id") or f"feature-{i}",
                nome=props.get("nome") or "(sem nome)",
                tipo=props.get("tipo") or "(sem tipo)",
                geometria=geom,
            )
        )
    if not barreiras:
        raise ErroExterno(f"Nenhuma barreira carregada de {caminho}")
    return barreiras


def barreiras_atingidas(
    rota: Rota, barreiras: list[Barreira], buffer_m: float = BUFFER_M_PADRAO
) -> list[Barreira]:
    """
    Projeta rota e barreiras para UTM local, aplica o buffer em metros na barreira
    e devolve as que intersectam a rota.

    Andar ao longo da barreira e atravessá-la dão o mesmo resultado: é `intersects`
    booleano puro, sem contagem de cruzamentos nem análise de ângulo.
    """
    crs = crs_utm_local(*rota.linha.centroid.coords[0])
    rota_m = para_metrico(rota.linha, crs)

    # Prefiltro barato em graus: evita projetar barreiras a quilômetros da rota.
    minx, miny, maxx, maxy = rota.linha.bounds
    minx -= RAIO_PREFILTRO_GRAUS
    miny -= RAIO_PREFILTRO_GRAUS
    maxx += RAIO_PREFILTRO_GRAUS
    maxy += RAIO_PREFILTRO_GRAUS

    atingidas: list[Barreira] = []
    for barreira in barreiras:
        bminx, bminy, bmaxx, bmaxy = barreira.geometria.bounds
        if bmaxx < minx or bminx > maxx or bmaxy < miny or bminy > maxy:
            continue
        area_influencia = para_metrico(barreira.geometria, crs).buffer(buffer_m)
        if rota_m.intersects(area_influencia):
            atingidas.append(barreira)
    return atingidas


# --------------------------------------------------------------------------- #
# Decisão
# --------------------------------------------------------------------------- #


def decidir(
    rota: Rota | None, atingidas: list[Barreira], escolheu_escola: bool
) -> Resultado:
    if escolheu_escola:
        return Resultado(False, "A responsável escolheu esta escola.", None, [])
    if atingidas:
        nomes = sorted({b.nome for b in atingidas})
        return Resultado(
            True,
            f"O menor caminho a pé passa por: {', '.join(nomes)}.",
            rota.distancia_m if rota else None,
            nomes,
        )
    return Resultado(
        False,
        "O menor caminho a pé não passa por nenhuma barreira física.",
        rota.distancia_m if rota else None,
        [],
    )


# --------------------------------------------------------------------------- #
# OpenRouteService
# --------------------------------------------------------------------------- #


def ler_api_key() -> str:
    chave = os.environ.get("ORS_API_KEY")
    if chave:
        return chave.strip()

    secrets = Path(__file__).parent / ".streamlit" / "secrets.toml"
    if secrets.exists():
        with open(secrets, "rb") as f:
            dados = tomllib.load(f)
        chave = dados.get("ORS_API_KEY") or dados.get("ors", {}).get("api_key")
        if chave:
            return str(chave).strip()

    raise ErroExterno(
        "Chave do OpenRouteService não encontrada.\n"
        "  export ORS_API_KEY='sua-chave'   (crie em openrouteservice.org)\n"
        "  ou rode com --offline para validar só a geometria, sem chamar a API."
    )


def _erro_http(resp: requests.Response, etapa: str) -> ErroExterno:
    if resp.status_code == 429:
        return ErroExterno(f"{etapa}: cota do OpenRouteService estourada (HTTP 429).")
    if resp.status_code in (401, 403):
        return ErroExterno(f"{etapa}: chave do OpenRouteService inválida (HTTP {resp.status_code}).")
    return ErroExterno(f"{etapa}: OpenRouteService respondeu HTTP {resp.status_code} — {resp.text[:200]}")


def geocodificar(texto: str, api_key: str, cep: str | None = None) -> list[Local]:
    """
    Candidatos ordenados por confiança, restritos ao Brasil e focados em São Paulo.

    O CEP entra no texto enviado: SP tem 96 distritos e milhares de nomes de rua
    repetidos entre eles, e sem CEP "Rua São João" tem dezenas de respostas plausíveis.
    """
    consulta = f"{texto}, {cep}" if cep else texto
    params = {
        "api_key": api_key,
        "text": consulta,
        "boundary.country": "BR",
        "focus.point.lon": CENTRO_SP[0],
        "focus.point.lat": CENTRO_SP[1],
        "size": 5,
    }
    try:
        resp = requests.get(ORS_GEOCODE, params=params, timeout=TIMEOUT_S)
    except requests.RequestException as e:
        raise ErroExterno(f"Geocodificação falhou na rede: {e}") from e
    if resp.status_code != 200:
        raise _erro_http(resp, "Geocodificação")

    locais: list[Local] = []
    for feature in resp.json().get("features", []):
        props = feature.get("properties") or {}
        # Pelias devolve o município em `locality`; descarta homônimos de outras cidades.
        if props.get("locality") and MUNICIPIO.lower() not in props["locality"].lower():
            continue
        lon, lat = feature["geometry"]["coordinates"]
        locais.append(
            Local(
                texto_original=consulta,
                endereco_formatado=props.get("label") or "(sem rótulo)",
                lat=lat,
                lon=lon,
                confianca=props.get("confidence"),
            )
        )
    if not locais:
        raise ErroExterno(f"Nenhum endereço em {MUNICIPIO} para: {consulta!r}")
    return locais


def rota_a_pe(origem: Local, destino: Local, api_key: str) -> Rota:
    corpo = {"coordinates": [[origem.lon, origem.lat], [destino.lon, destino.lat]]}
    cabecalhos = {"Authorization": api_key, "Content-Type": "application/json"}
    try:
        resp = requests.post(ORS_DIRECTIONS, json=corpo, headers=cabecalhos, timeout=TIMEOUT_S)
    except requests.RequestException as e:
        raise ErroExterno(f"Roteamento falhou na rede: {e}") from e
    if resp.status_code != 200:
        raise _erro_http(resp, "Roteamento")

    features = resp.json().get("features") or []
    if not features:
        raise ErroExterno("O OpenRouteService não achou rota a pé entre os dois pontos.")
    feature = features[0]
    resumo = feature["properties"]["summary"]
    return Rota(
        linha=shape(feature["geometry"]),
        distancia_m=float(resumo["distance"]),
        duracao_s=float(resumo["duration"]),
    )


# --------------------------------------------------------------------------- #
# Modo offline — geometria sintética, sem API
# --------------------------------------------------------------------------- #


def local_offline(texto: str, cep: str, coords: tuple[float, float]) -> Local:
    lon, lat = coords
    return Local(
        texto_original=f"{texto}, {cep}",
        endereco_formatado=f"[OFFLINE] {texto}",
        lat=lat,
        lon=lon,
        confianca=None,
    )


def rota_offline(origem: Local, destino: Local) -> Rota:
    """
    Linha reta entre A e B. NÃO é a rota a pé: serve só para exercitar projeção,
    buffer e interseção sem depender do OpenRouteService.
    """
    linha = LineString([(origem.lon, origem.lat), (destino.lon, destino.lat)])
    crs = crs_utm_local(*linha.centroid.coords[0])
    return Rota(linha=linha, distancia_m=para_metrico(linha, crs).length, duracao_s=0.0)


# --------------------------------------------------------------------------- #
# Saída no terminal
# --------------------------------------------------------------------------- #


def mostrar_local(rotulo: str, candidatos: list[Local]) -> Local:
    """
    Imprime o endereço formatado — a proteção mais eficaz contra erro de geocodificação.
    Quando há empate de score, mostra a lista em vez de escolher em silêncio.
    """
    escolhido = candidatos[0]
    print(f"  {rotulo}")
    print(f"    texto enviado ...: {escolhido.texto_original}")
    print(f"    endereço achado .: {escolhido.endereco_formatado}")
    print(f"    coordenada ......: {escolhido.lat:.6f}, {escolhido.lon:.6f}")
    if escolhido.confianca is not None:
        print(f"    confiança .......: {escolhido.confianca:.2f}")

    empatados = [
        c
        for c in candidatos[1:]
        if c.confianca is not None
        and escolhido.confianca is not None
        and escolhido.confianca - c.confianca <= MARGEM_EMPATE_CONFIANCA
    ]
    if empatados:
        print("    !! AMBÍGUO — outros candidatos com score próximo:")
        for c in empatados:
            print(f"       - {c.endereco_formatado} (confiança {c.confianca:.2f})")
        print("       Confira o CEP antes de confiar na decisão.")
    return escolhido


def rodar_caso(nome: str, caso: Caso, barreiras: list[Barreira], buffer_m: float, offline: bool) -> bool:
    print("=" * 78)
    print(f"CASO {nome} — {caso.descricao}")
    print("=" * 78)

    if offline:
        casa = local_offline(caso.endereco_casa, caso.cep_casa, caso.coords_casa)
        escola = local_offline(caso.endereco_escola, caso.cep_escola, caso.coords_escola)
        mostrar_local("CASA", [casa])
        mostrar_local("ESCOLA", [escola])
        rota = rota_offline(casa, escola)
        print("\n  MODO OFFLINE: rota é uma linha reta, não o menor caminho a pé.")
        print("  Serve para validar projeção/buffer/interseção — não vale como decisão real.")
    else:
        api_key = ler_api_key()
        casa = mostrar_local("CASA", geocodificar(caso.endereco_casa, api_key, caso.cep_casa))
        escola = mostrar_local("ESCOLA", geocodificar(caso.endereco_escola, api_key, caso.cep_escola))
        rota = rota_a_pe(casa, escola, api_key)

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
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--caso", choices=sorted(CASOS), default="1", help="qual caso fixo rodar (padrão: 1)")
    parser.add_argument("--todos", action="store_true", help="roda os três casos em sequência")
    parser.add_argument("--buffer", type=float, default=BUFFER_M_PADRAO, help="buffer da barreira em metros (padrão: 5)")
    parser.add_argument("--geojson", type=Path, default=ARQUIVO_BARREIRAS, help="arquivo de barreiras")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="não chama o OpenRouteService: usa coordenadas fixas e rota em linha reta",
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
