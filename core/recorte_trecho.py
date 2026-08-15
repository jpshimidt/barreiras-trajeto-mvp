"""Recorte de geometria de barreira por faixa de número de porta."""

from __future__ import annotations

import re
from dataclasses import dataclass

from shapely.geometry import LineString, Point
from shapely.ops import substring

_NUMERO_RE = re.compile(r"^\d+$")


@dataclass(frozen=True)
class RegistroTrecho:
    """Uma linha do cadastro de barreiras (ruas_barreira.txt)."""

    nome: str
    numero_inicio: int | None = None
    numero_fim: int | None = None
    paridade: str | None = None  # par | impar | ambos | None

    def tem_faixa(self) -> bool:
        return self.numero_inicio is not None or self.numero_fim is not None


@dataclass(frozen=True)
class MarcaNumero:
    """Número de porta projetado sobre um eixo viário (fração 0–1 do comprimento)."""

    numero: int
    fracao: float


def parse_linha_trecho(linha: str) -> RegistroTrecho | None:
    """
    Interpreta uma linha do cadastro.

    Formatos aceitos:
      - ``Marginal Tietê`` — rua inteira
      - ``Av. X;100;500`` — do nº 100 ao 500
      - ``Av. X;100;500;par`` — só números pares no intervalo
    """
    texto = linha.strip()
    if not texto or texto.startswith("#"):
        return None

    partes = [p.strip() for p in texto.split(";")]
    nome = partes[0]
    if not nome:
        return None

    def _int_opcional(valor: str | None) -> int | None:
        if not valor:
            return None
        if not _NUMERO_RE.match(valor):
            raise ValueError(f"número inválido em trecho de barreira: {valor!r}")
        return int(valor)

    numero_inicio = _int_opcional(partes[1]) if len(partes) > 1 else None
    numero_fim = _int_opcional(partes[2]) if len(partes) > 2 else None
    paridade = partes[3].lower() if len(partes) > 3 and partes[3] else None
    if paridade and paridade not in {"par", "impar", "ambos"}:
        raise ValueError(f"paridade inválida: {paridade!r} (use par, impar ou ambos)")

    if numero_inicio is not None and numero_fim is not None and numero_inicio > numero_fim:
        numero_inicio, numero_fim = numero_fim, numero_inicio

    return RegistroTrecho(nome, numero_inicio, numero_fim, paridade)


def numero_compativel_paridade(numero: int, paridade: str | None) -> bool:
    if not paridade or paridade == "ambos":
        return True
    if paridade == "par":
        return numero % 2 == 0
    return numero % 2 == 1


def fracao_por_numero(marcas: list[MarcaNumero], numero: int) -> float | None:
    """Interpola a posição ao longo do eixo para um número de porta."""
    if not marcas:
        return None
    ordenadas = sorted(marcas, key=lambda m: m.numero)
    if numero <= ordenadas[0].numero:
        return ordenadas[0].fracao
    if numero >= ordenadas[-1].numero:
        return ordenadas[-1].fracao

    for esq, dir in zip(ordenadas, ordenadas[1:]):
        if esq.numero <= numero <= dir.numero:
            if dir.numero == esq.numero:
                return esq.fracao
            proporcao = (numero - esq.numero) / (dir.numero - esq.numero)
            return esq.fracao + proporcao * (dir.fracao - esq.fracao)
    return None


def recortar_linha_por_numeros(
    linha: LineString,
    marcas: list[MarcaNumero],
    numero_inicio: int | None,
    numero_fim: int | None,
    *,
    paridade: str | None = None,
) -> LineString | None:
    """
    Recorta um trecho da linha entre dois números de porta.

    Retorna None se não houver marcas OSM suficientes para localizar o intervalo.
    """
    if linha.is_empty or linha.length == 0:
        return None
    if numero_inicio is None and numero_fim is None:
        return linha

    marcas_validas = [m for m in marcas if numero_compativel_paridade(m.numero, paridade)]
    if not marcas_validas:
        return None

    inicio = numero_inicio if numero_inicio is not None else marcas_validas[0].numero
    fim = numero_fim if numero_fim is not None else marcas_validas[-1].numero
    if inicio > fim:
        inicio, fim = fim, inicio

    frac_ini = fracao_por_numero(marcas_validas, inicio)
    frac_fim = fracao_por_numero(marcas_validas, fim)
    if frac_ini is None or frac_fim is None:
        return None

    frac_ini = max(0.0, min(1.0, frac_ini))
    frac_fim = max(0.0, min(1.0, frac_fim))
    if frac_ini > frac_fim:
        frac_ini, frac_fim = frac_fim, frac_ini
    if frac_fim - frac_ini < 1e-9:
        return None

    return substring(linha, frac_ini, frac_fim, normalized=True)


def marcas_de_coordenadas(
    linha: LineString, pontos: list[tuple[int, float, float]]
) -> list[MarcaNumero]:
    """
    Projeta pontos (número, lon, lat) sobre a linha e devolve marcas ordenadas.

    Usado pelo importador com nós OSM ``addr:housenumber``.
    """
    if linha.is_empty:
        return []

    marcas: list[MarcaNumero] = []
    comprimento = linha.length
    if comprimento == 0:
        return []

    for numero, lon, lat in pontos:
        ponto = Point(lon, lat)
        fracao = linha.project(ponto, normalized=True)
        marcas.append(MarcaNumero(numero=numero, fracao=fracao))
    return sorted(marcas, key=lambda m: m.numero)


def rotulo_trecho(
    nome: str,
    numero_inicio: int | None,
    numero_fim: int | None,
    paridade: str | None = None,
) -> str:
    """Rótulo legível para o usuário final."""
    if numero_inicio is None and numero_fim is None:
        return nome
    if numero_inicio is not None and numero_fim is not None:
        base = f"{nome} (nº {numero_inicio}–{numero_fim})"
    elif numero_inicio is not None:
        base = f"{nome} (a partir do nº {numero_inicio})"
    else:
        base = f"{nome} (até o nº {numero_fim})"
    if paridade and paridade != "ambos":
        base += f", {paridade}"
    return base
