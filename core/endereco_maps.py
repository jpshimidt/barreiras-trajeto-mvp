"""
Geocodificação no padrão Google Maps — módulo canônico.

`app.py` importa daqui diretamente para evitar cache de versão antiga de
`core.geocode` no Streamlit Cloud.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

import requests

from core.erros import ErroExterno
from core.ors import TIMEOUT_S, erro_http

MUNICIPIO = "São Paulo"
CENTRO_SP = (-46.6333, -23.5505)  # (lon, lat) — focus.point
MARGEM_EMPATE_CONFIANCA = 0.10
MAX_CANDIDATOS = 8
CEP_RE = re.compile(r"\b(\d{5})-?(\d{3})\b")
# Padrão Google Maps: R. Exemplo, 355 - Bairro, São Paulo - SP, 00000-000
EXEMPLO_ENDERECO_MAPS = "R. Voluntários da Pátria, 1000 - Santana, São Paulo - SP, 02011-000"
MAPS_RE = re.compile(
    r"^(?P<logradouro>.+?),\s*(?P<numero>\d+)\s*-\s*(?P<bairro>.+?),\s*"
    r"(?P<cidade>.+?)\s*-\s*(?P<uf>[A-Z]{2})(?:,\s*(?P<cep>\d{5}-?\d{3}))?\s*$",
    re.IGNORECASE,
)
MIN_ADEQUACAO_AUTO = 60
MARGEM_ADEQUACAO = 15
MIN_ADEQUACAO_ESCOLHA = 25

URL = "https://api.openrouteservice.org/geocode/search"


@dataclass
class Local:
    texto_original: str
    endereco_formatado: str  # o que o geocodificador entendeu — mostrar ao usuário
    lat: float
    lon: float
    confianca: float | None
    adequacao: int | None = None  # compatibilidade com o endereço colado; maior = melhor


@dataclass(frozen=True)
class EnderecoMaps:
    texto: str
    logradouro: str | None
    numero: str | None
    bairro: str | None
    cidade: str | None
    uf: str | None
    cep: str | None


@dataclass(frozen=True)
class ResolucaoGeocode:
    """Resultado da escolha automática ou manual de um candidato."""

    local: Local | None
    opcoes: tuple[Local, ...]
    endereco: EnderecoMaps
    automatico: bool


def extrair_cep(texto: str) -> str | None:
    """Extrai CEP no formato 00000-000 de um endereço colado."""
    match = CEP_RE.search(texto)
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2)}"


def _cep_presente(texto: str, cep: str) -> bool:
    return re.sub(r"\D", "", cep) in re.sub(r"\D", "", texto)


def _sem_acentos(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(ch for ch in texto if not unicodedata.combining(ch))


def _normalizar_rua(nome: str) -> str:
    nome = _sem_acentos(nome.lower().strip())
    nome = re.sub(r"^(r\.?|rua|av\.?|avenida|al\.?|trav\.?|travessa)\s+", "", nome)
    return re.sub(r"\s+", " ", nome)


def parse_endereco_maps(texto: str) -> EnderecoMaps:
    """
    Interpreta endereço colado no padrão Google Maps.

    Ex.: R. Ana Soares Barcelos, 355 - Vila Venditti, São Paulo - SP, 07031-070
    """
    texto = " ".join(texto.strip().split())
    match = MAPS_RE.match(texto)
    if match:
        grupos = match.groupdict()
        cep = grupos.get("cep")
        return EnderecoMaps(
            texto=texto,
            logradouro=grupos["logradouro"].strip(),
            numero=grupos["numero"].strip(),
            bairro=grupos["bairro"].strip(),
            cidade=grupos["cidade"].strip(),
            uf=grupos["uf"].strip().upper(),
            cep=f"{cep[:5]}-{cep[5:]}" if cep and "-" not in cep else cep,
        )
    return EnderecoMaps(
        texto=texto,
        logradouro=None,
        numero=None,
        bairro=None,
        cidade=None,
        uf=None,
        cep=extrair_cep(texto),
    )


def montar_consulta(texto: str, cep: str | None = None) -> str:
    """Monta a consulta ao geocodificador."""
    endereco = parse_endereco_maps(texto)
    cep = (cep or endereco.cep or "").strip() or None
    if cep and not _cep_presente(endereco.texto, cep):
        return f"{endereco.texto}, {cep}"
    return endereco.texto


def _consulta_alternativa(endereco: EnderecoMaps) -> str | None:
    """Formato número-primeiro costuma achar o portão certo no Pelias."""
    if not (endereco.logradouro and endereco.numero and endereco.bairro):
        return None
    partes = [
        f"{endereco.numero} {endereco.logradouro}",
        endereco.bairro,
        MUNICIPIO,
        "SP",
    ]
    if endereco.cep:
        partes.append(endereco.cep)
    return ", ".join(partes)


def _candidato_tem_endereco(props: dict) -> bool:
    """Descarta resultados genéricos como 'São Paulo, Brazil' sem rua ou número."""
    layer = (props.get("layer") or "").lower()
    if layer in {"locality", "region", "country", "macroregion", "county"}:
        return False

    street = props.get("street")
    housenumber = props.get("housenumber")
    name = (props.get("name") or "").strip()
    label = (props.get("label") or "").strip().lower()

    if housenumber or street:
        return True
    if layer in {"address", "venue"} and name:
        return True
    if layer == "street" and name:
        return True

    genericos = {
        "são paulo, brazil",
        "sao paulo, brazil",
        "são paulo, brasil",
        "sao paulo, brasil",
    }
    return label not in genericos


def _ruas_equivalentes(informada: str, candidata: str) -> bool:
    return _normalizar_rua(informada) == _normalizar_rua(candidata)


def _rua_estendida(informada: str, candidata: str) -> bool:
    """Borges Ladário contém Borges, mas não é a mesma rua."""
    ni = _normalizar_rua(informada)
    nc = _normalizar_rua(candidata)
    return ni != nc and ni in nc


def pontuar_candidato(props: dict, endereco: EnderecoMaps) -> int:
    """Quanto maior, mais o candidato combina com o endereço colado."""
    label = (props.get("label") or "").lower()
    street = props.get("street") or props.get("name") or ""
    score = 0

    if endereco.cep:
        cand_cep = props.get("postalcode") or ""
        if _cep_presente(cand_cep, endereco.cep) or _cep_presente(label, endereco.cep):
            score += 40

    if endereco.logradouro:
        if _ruas_equivalentes(endereco.logradouro, street):
            score += 35
        elif _ruas_equivalentes(endereco.logradouro, label):
            score += 30
        elif _rua_estendida(endereco.logradouro, street) or _rua_estendida(endereco.logradouro, label):
            score -= 15
        elif _normalizar_rua(endereco.logradouro) in _normalizar_rua(label):
            score += 10

    if endereco.numero:
        housenumber = str(props.get("housenumber") or "")
        if housenumber == endereco.numero:
            score += 25
        elif props.get("layer") == "street":
            score -= 5

    if endereco.bairro:
        bairro = _sem_acentos(endereco.bairro.lower())
        for campo in (props.get("neighbourhood"), props.get("borough"), label):
            if campo and bairro in _sem_acentos(str(campo).lower()):
                score += 20
                break

    confianca = props.get("confidence")
    if confianca is not None:
        score += int(confianca * 10)

    return score


def local_de_feature(
    feature: dict, texto_original: str, endereco: EnderecoMaps | None = None
) -> Local | None:
    """
    Converte uma feature do Pelias em `Local`, ou None se não for de São Paulo capital.

    `locality` é o município no Pelias. Quando ele vem preenchido e é outra cidade,
    o candidato é descartado — homônimo de rua em Guarulhos não pode virar decisão.
    """
    props = feature.get("properties") or {}
    locality = props.get("locality")
    if locality and MUNICIPIO.lower() not in locality.lower():
        return None
    if not _candidato_tem_endereco(props):
        return None

    coords = (feature.get("geometry") or {}).get("coordinates")
    if not coords or len(coords) < 2:
        return None

    lon, lat = coords[0], coords[1]
    adequacao = pontuar_candidato(props, endereco) if endereco else None
    return Local(
        texto_original=texto_original,
        endereco_formatado=props.get("label") or "(sem rótulo)",
        lat=float(lat),
        lon=float(lon),
        confianca=props.get("confidence"),
        adequacao=adequacao,
    )


def candidatos_ambiguos(
    candidatos: list[Local], margem: float = MARGEM_EMPATE_CONFIANCA
) -> list[Local]:
    """
    Candidatos que empatam com o primeiro dentro da margem de confiança do ORS.

    Preferir `resolver_geocodificacao`, que usa a adequação ao endereço colado.
    """
    if len(candidatos) < 2:
        return []
    melhor = candidatos[0]
    if melhor.confianca is None:
        return []
    return [
        c
        for c in candidatos[1:]
        if c.confianca is not None and melhor.confianca - c.confianca <= margem
    ]


def _ordenar_candidatos(candidatos: list[Local]) -> list[Local]:
    return sorted(
        candidatos,
        key=lambda local: (
            local.adequacao if local.adequacao is not None else -999,
            local.confianca if local.confianca is not None else 0.0,
        ),
        reverse=True,
    )


def resolver_geocodificacao(texto: str, candidatos: list[Local]) -> ResolucaoGeocode:
    """
    Decide se o melhor candidato pode ser aceito sozinho ou se o usuário precisa escolher.

    Só escolhe automaticamente quando a adequação ao endereço colado é clara.
    """
    endereco = parse_endereco_maps(texto)
    ordenados = _ordenar_candidatos(candidatos)
    if not ordenados:
        return ResolucaoGeocode(None, (), endereco, automatico=False)

    melhor = ordenados[0]
    adequacao = melhor.adequacao or 0
    if adequacao < MIN_ADEQUACAO_ESCOLHA:
        return ResolucaoGeocode(None, tuple(ordenados), endereco, automatico=False)

    if len(ordenados) == 1:
        return ResolucaoGeocode(melhor, (), endereco, automatico=adequacao >= MIN_ADEQUACAO_AUTO)

    segundo = ordenados[1]
    gap = adequacao - (segundo.adequacao or 0)
    if adequacao >= MIN_ADEQUACAO_AUTO and gap >= MARGEM_ADEQUACAO:
        return ResolucaoGeocode(melhor, (), endereco, automatico=True)

    empatados = [
        c
        for c in ordenados
        if adequacao - (c.adequacao or 0) <= MARGEM_ADEQUACAO and (c.adequacao or 0) >= MIN_ADEQUACAO_ESCOLHA
    ]
    if len(empatados) == 1 and empatados[0].adequacao and empatados[0].adequacao >= MIN_ADEQUACAO_AUTO:
        return ResolucaoGeocode(empatados[0], (), endereco, automatico=True)

    return ResolucaoGeocode(None, tuple(empatados or ordenados), endereco, automatico=False)


def _buscar_pelias(consulta: str, api_key: str, cep: str | None = None) -> list[dict]:
    params = {
        "api_key": api_key,
        "text": consulta,
        "boundary.country": "BR",
        "focus.point.lon": CENTRO_SP[0],
        "focus.point.lat": CENTRO_SP[1],
        "layers": "address,venue,street",
        "size": MAX_CANDIDATOS,
    }
    if cep:
        params["boundary.postalcode"] = re.sub(r"\D", "", cep)
    try:
        resp = requests.get(URL, params=params, timeout=TIMEOUT_S)
    except requests.RequestException as e:
        raise ErroExterno(f"Geocodificação falhou na rede: {e}") from e
    if resp.status_code != 200:
        raise erro_http(resp, "Geocodificação")
    return resp.json().get("features") or []


def geocodificar(texto: str, api_key: str, cep: str | None = None) -> list[Local]:
    """Candidatos ordenados por adequação ao endereço colado, depois confiança do ORS."""
    endereco = parse_endereco_maps(texto)
    consulta = montar_consulta(texto, cep)
    features = _buscar_pelias(consulta, api_key, endereco.cep)

    alternativa = _consulta_alternativa(endereco)
    if alternativa and alternativa != consulta:
        features.extend(_buscar_pelias(alternativa, api_key, endereco.cep))

    vistos: set[tuple[float, float, str]] = set()
    locais: list[Local] = []
    for feature in features:
        local = local_de_feature(feature, consulta, endereco)
        if local is None:
            continue
        chave = (round(local.lat, 6), round(local.lon, 6), local.endereco_formatado)
        if chave in vistos:
            continue
        vistos.add(chave)
        locais.append(local)

    locais = _ordenar_candidatos(locais)
    if not locais:
        raise ErroExterno(
            f"Nenhum endereço em {MUNICIPIO} para: {consulta!r}\n"
            f"  Cole o endereço como no Google Maps, por exemplo:\n"
            f"  {EXEMPLO_ENDERECO_MAPS}"
        )
    return locais
