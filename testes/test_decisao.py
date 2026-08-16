"""
Testes do núcleo. Nenhum toca a rede: geometrias sintéticas e respostas de API
montadas à mão. Rodar com `pytest` na raiz do repositório.
"""

from __future__ import annotations

import json
import math

import pytest
from shapely.geometry import LineString, MultiLineString

from core.barreiras import Barreira, barreiras_atingidas, carregar_barreiras
from core.decisao import decidir
from core.erros import ErroExterno
from core.geo import crs_utm_local, para_metrico
from core.geocode import (
    EnderecoMaps,
    EXEMPLO_ENDERECO_MAPS,
    Local,
    candidatos_ambiguos,
    extrair_cep,
    local_de_feature,
    montar_consulta,
    parse_endereco_maps,
    pontuar_candidato,
    resolver_geocodificacao,
)
from core.routing import Rota, rota_de_geojson, rota_reta

# Referência em Santana, Zona Norte. 1 grau de latitude ~ 110.574 m nesta faixa.
LAT = -23.5100
LON = -46.6280
METRO_EM_GRAUS_LAT = 1 / 110574


def barreira_leste_oeste(nome: str = "Marginal Tietê", lat: float = LAT) -> Barreira:
    """Barreira reta no sentido leste-oeste, com ~1 km de extensão."""
    return Barreira(
        id=f"{nome}-01",
        nome=nome,
        tipo="via expressa",
        geometria=LineString([(LON - 0.005, lat), (LON + 0.005, lat)]),
    )


def rota(coords: list[tuple[float, float]], distancia_m: float = 1000.0) -> Rota:
    return Rota(linha=LineString(coords), distancia_m=distancia_m, duracao_s=900.0)


def rota_paralela(distancia_m: float, lat: float = LAT) -> Rota:
    """Rota reta paralela à barreira, afastada `distancia_m` metros ao sul."""
    deslocamento = distancia_m * METRO_EM_GRAUS_LAT
    return rota([(LON - 0.003, lat - deslocamento), (LON + 0.003, lat - deslocamento)])


def rota_transversal(lat: float = LAT) -> Rota:
    """Rota norte-sul que corta a barreira leste-oeste."""
    return rota([(LON, lat + 0.003), (LON, lat - 0.003)])


# --------------------------------------------------------------------------- #
# Tabela de decisão — as três linhas
# --------------------------------------------------------------------------- #


def test_escolheu_a_escola_nao_tem_direito_mesmo_tocando_barreira():
    resultado = decidir(rota_transversal(), [barreira_leste_oeste()], escolheu_escola=True)

    assert resultado.tem_direito is False
    assert resultado.motivo == "A responsável escolheu esta escola."
    assert resultado.barreiras_atingidas == []
    # A flag encerra a análise: nem a distância é reportada.
    assert resultado.distancia_m is None


def test_nao_escolheu_e_toca_barreira_tem_direito():
    resultado = decidir(rota_transversal(), [barreira_leste_oeste()], escolheu_escola=False)

    assert resultado.tem_direito is True
    assert resultado.barreiras_atingidas == ["Marginal Tietê"]
    assert "Marginal Tietê" in resultado.motivo
    assert resultado.distancia_m == 1000.0


def test_nao_escolheu_e_nao_toca_barreira_nao_tem_direito():
    resultado = decidir(rota_transversal(), [], escolheu_escola=False)

    assert resultado.tem_direito is False
    assert resultado.barreiras_atingidas == []
    assert resultado.motivo == "O menor caminho a pé não passa por nenhuma barreira física."
    assert resultado.distancia_m == 1000.0


def test_trecho_com_faixa_aparece_no_motivo():
    trecho = Barreira(
        "t1",
        "Avenida Inajar de Souza",
        "avenida",
        LineString([(LON, LAT), (LON + 0.01, LAT)]),
        numero_inicio=100,
        numero_fim=500,
    )
    resultado = decidir(rota_transversal(), [trecho], escolheu_escola=False)
    assert "Avenida Inajar de Souza (nº 100–500)" in resultado.motivo
    assert resultado.barreiras_atingidas == ["Avenida Inajar de Souza (nº 100–500)"]


def test_avenida_fragmentada_aparece_uma_vez_so():
    """Uma avenida vem em dezenas de ways do OSM; o usuário lê o nome uma vez."""
    trechos = [
        Barreira("t1", "Avenida Inajar de Souza", "avenida", LineString([(0, 0), (1, 1)])),
        Barreira("t2", "Avenida Inajar de Souza", "avenida", LineString([(1, 1), (2, 2)])),
        Barreira("t3", "Marginal Tietê", "via expressa", LineString([(0, 1), (1, 2)])),
    ]
    resultado = decidir(rota_transversal(), trechos, escolheu_escola=False)

    assert resultado.barreiras_atingidas == ["Avenida Inajar de Souza", "Marginal Tietê"]


def test_sem_rota_nao_quebra():
    resultado = decidir(None, [], escolheu_escola=False)

    assert resultado.tem_direito is False
    assert resultado.distancia_m is None


# --------------------------------------------------------------------------- #
# Projeção — o buffer tem de ser em metros, nunca em graus
# --------------------------------------------------------------------------- #


def test_sao_paulo_cai_na_utm_23_sul():
    assert crs_utm_local(LON, LAT).to_epsg() == 32723


def test_hemisferio_norte_usa_faixa_326xx():
    assert crs_utm_local(-74.0, 40.7).to_epsg() == 32618


def test_buffer_em_graus_seria_absurdo():
    """
    Regressão do erro mais caro do projeto: .buffer(5) em WGS84 gera 5 GRAUS.
    O buffer projetado tem de ficar na ordem de metros, não de centenas de km.
    """
    geometria = barreira_leste_oeste().geometria

    largura_em_graus = geometria.buffer(5).bounds[3] - geometria.buffer(5).bounds[1]
    assert largura_em_graus > 9  # ~10 graus = mais de 1.000 km

    # Área de um buffer de raio r sobre uma linha de comprimento L: 2rL + pi*r².
    # Medir a área em vez da altura do bbox porque a linha projetada não fica
    # horizontal: a latitude constante inclina ~11 m por km nesta longitude,
    # efeito da convergência de meridianos longe do meridiano central da zona.
    projetada = para_metrico(geometria, crs_utm_local(LON, LAT))
    esperado = 2 * 5 * projetada.length + math.pi * 5**2

    assert math.isclose(projetada.buffer(5).area, esperado, rel_tol=1e-3)


def test_projecao_preserva_comprimento_em_metros():
    """1 km desenhado em graus tem de virar ~1 km projetado."""
    linha = LineString([(LON, LAT), (LON, LAT - 1000 * METRO_EM_GRAUS_LAT)])
    comprimento = para_metrico(linha, crs_utm_local(LON, LAT)).length

    assert math.isclose(comprimento, 1000, rel_tol=0.01)


# --------------------------------------------------------------------------- #
# Interseção com o buffer
# --------------------------------------------------------------------------- #


def test_rota_que_atravessa_toca_a_barreira():
    atingidas = barreiras_atingidas(rota_transversal(), [barreira_leste_oeste()], buffer_m=5.0)

    assert [b.nome for b in atingidas] == ["Marginal Tietê"]


def test_caminhar_ao_longo_conta_igual_a_atravessar():
    """
    Rota paralela à barreira, a 3 m dela: nunca cruza, mas encosta.
    A decisão é `intersects` puro — não se distingue travessia de percurso paralelo.
    """
    atingidas = barreiras_atingidas(rota_paralela(3), [barreira_leste_oeste()], buffer_m=5.0)

    assert len(atingidas) == 1


@pytest.mark.parametrize(
    "distancia_m, deve_tocar",
    [(0.5, True), (3.0, True), (4.9, True), (5.1, False), (20.0, False), (500.0, False)],
)
def test_o_corte_do_buffer_fica_exatamente_em_5_metros(distancia_m, deve_tocar):
    atingidas = barreiras_atingidas(rota_paralela(distancia_m), [barreira_leste_oeste()], buffer_m=5.0)

    assert bool(atingidas) is deve_tocar


def test_buffer_maior_alcanca_rota_mais_distante():
    """Buffer generoso demais faz a rota 'encostar' em via que ela não usa."""
    r = rota_paralela(12)
    barreiras = [barreira_leste_oeste()]

    assert barreiras_atingidas(r, barreiras, buffer_m=5.0) == []
    assert len(barreiras_atingidas(r, barreiras, buffer_m=20.0)) == 1


def test_barreira_distante_e_descartada_pelo_prefiltro():
    """Barreira do outro lado da cidade não pode entrar no resultado."""
    longe = Barreira("x", "Avenida Longe", "avenida", LineString([(-46.75, -23.60), (-46.74, -23.60)]))
    atingidas = barreiras_atingidas(rota_transversal(), [barreira_leste_oeste(), longe], buffer_m=5.0)

    assert [b.nome for b in atingidas] == ["Marginal Tietê"]


def test_multilinestring_e_aceita():
    barreira = Barreira(
        "m",
        "Barreira Fragmentada",
        "avenida",
        MultiLineString([[(LON - 0.005, LAT), (LON, LAT)], [(LON, LAT), (LON + 0.005, LAT)]]),
    )
    assert len(barreiras_atingidas(rota_transversal(), [barreira], buffer_m=5.0)) == 1


def test_buffer_negativo_e_recusado():
    with pytest.raises(ValueError):
        barreiras_atingidas(rota_transversal(), [barreira_leste_oeste()], buffer_m=-1.0)


# --------------------------------------------------------------------------- #
# Carga do GeoJSON
# --------------------------------------------------------------------------- #


def escrever_geojson(tmp_path, features):
    caminho = tmp_path / "barreiras.geojson"
    caminho.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8"
    )
    return caminho


def test_carrega_propriedades_da_barreira(tmp_path):
    caminho = escrever_geojson(
        tmp_path,
        [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[LON, LAT], [LON + 0.01, LAT]]},
                "properties": {
                    "id": "abc",
                    "nome": "Marginal Tietê",
                    "tipo": "via expressa",
                    "numero_inicio": 100,
                    "numero_fim": 500,
                    "paridade": "par",
                },
            }
        ],
    )
    (barreira,) = carregar_barreiras(caminho)

    assert (barreira.id, barreira.nome, barreira.tipo) == ("abc", "Marginal Tietê", "via expressa")
    assert barreira.numero_inicio == 100
    assert barreira.numero_fim == 500
    assert barreira.paridade == "par"
    assert barreira.rotulo == "Marginal Tietê (nº 100–500), par"


def test_cadastro_vazio_e_erro_nao_resposta_negativa(tmp_path):
    """
    Um GeoJSON sem barreiras daria 'sem direito' para todo mundo, em silêncio.
    Tem de estourar erro.
    """
    with pytest.raises(ErroExterno):
        carregar_barreiras(escrever_geojson(tmp_path, []))


def test_feature_sem_geometria_e_ignorada(tmp_path):
    caminho = escrever_geojson(
        tmp_path,
        [
            {"type": "Feature", "geometry": None, "properties": {"nome": "Fantasma"}},
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[LON, LAT], [LON + 0.01, LAT]]},
                "properties": {"nome": "Real"},
            },
        ],
    )
    assert [b.nome for b in carregar_barreiras(caminho)] == ["Real"]


def test_arquivo_inexistente_vira_erro_externo(tmp_path):
    with pytest.raises(ErroExterno):
        carregar_barreiras(tmp_path / "nao-existe.geojson")


def test_o_geojson_versionado_carrega():
    """O arquivo real do repositório tem de estar íntegro."""
    barreiras = carregar_barreiras("dados/barreiras.geojson")

    assert len(barreiras) >= 3
    assert "Marginal Tietê" in {b.nome for b in barreiras}


# --------------------------------------------------------------------------- #
# Geocodificação — ambiguidade de nomes de rua em SP
# --------------------------------------------------------------------------- #


def test_cep_entra_no_texto_enviado():
    assert montar_consulta("Rua São João, 100", "01035-000") == "Rua São João, 100, 01035-000"


def test_cep_extraido_do_formato_maps():
    texto = "R. Voluntários da Pátria, 1000 - Santana, São Paulo - SP, 02011-000"
    assert extrair_cep(texto) == "02011-000"
    assert montar_consulta(texto) == texto


def test_parse_endereco_maps_normaliza_espacos():
    endereco = parse_endereco_maps("  Rua   Borges, 353 - Parada Inglesa, São Paulo - SP, 02247-000  ")
    assert endereco.texto == "Rua Borges, 353 - Parada Inglesa, São Paulo - SP, 02247-000"
    assert endereco.logradouro == "Rua Borges"
    assert endereco.numero == "353"
    assert endereco.bairro == "Parada Inglesa"
    assert endereco.cep == "02247-000"


def test_parse_endereco_maps_aceita_r_borges():
    endereco = parse_endereco_maps("R. Borges, 353 - Parada Inglesa, São Paulo - SP, 02247-000")
    assert endereco.logradouro == "R. Borges"
    assert endereco.numero == "353"
    assert endereco.cep == "02247-000"


def test_pontuacao_penaliza_rua_sem_numero_quando_informado():
    endereco = EnderecoMaps(
        texto="R. Borges, 353 - Parada Inglesa, São Paulo - SP, 02247-000",
        logradouro="R. Borges",
        numero="353",
        bairro="Parada Inglesa",
        cidade="São Paulo",
        uf="SP",
        cep="02247-000",
    )
    com_numero = pontuar_candidato(
        {
            "label": "353, Rua Borges, Parada Inglesa, São Paulo",
            "street": "Rua Borges",
            "housenumber": "353",
            "postalcode": "02247-000",
            "neighbourhood": "Parada Inglesa",
            "confidence": 0.7,
        },
        endereco,
    )
    so_rua = pontuar_candidato(
        {
            "label": "Rua Borges, Tucuruvi, São Paulo",
            "street": "Rua Borges",
            "postalcode": "02247-000",
            "neighbourhood": "Parada Inglesa",
            "layer": "street",
            "confidence": 0.7,
        },
        endereco,
    )
    assert com_numero > so_rua


def test_parse_endereco_maps_sem_numero():
    endereco = parse_endereco_maps(
        "R. Cruz de Malta - Parada Inglesa, São Paulo - SP, Brasil"
    )
    assert endereco.logradouro == "R. Cruz de Malta"
    assert endereco.numero is None
    assert endereco.bairro == "Parada Inglesa"
    assert endereco.uf == "SP"


def test_parse_endereco_maps_aceita_sem_sp_e_cep_sem_hifen():
    """Colagem comum do Google Maps no celular: sem ' - SP' e CEP contínuo."""
    endereco = parse_endereco_maps("Rua Borges, 353 - Parada Inglesa, São paulo, 02247000")
    assert endereco.logradouro == "Rua Borges"
    assert endereco.numero == "353"
    assert endereco.bairro == "Parada Inglesa"
    assert endereco.uf == "SP"
    assert endereco.cep == "02247-000"


def test_pontuacao_prefere_rua_exata_e_penaliza_homonimo():
    endereco = EnderecoMaps(
        texto="Rua Borges, 353 - Parada Inglesa, São Paulo - SP, 02247-000",
        logradouro="Rua Borges",
        numero="353",
        bairro="Parada Inglesa",
        cidade="São Paulo",
        uf="SP",
        cep="02247-000",
    )
    exato = pontuar_candidato(
        {
            "label": "353, Rua Borges, Parada Inglesa, São Paulo",
            "street": "Rua Borges",
            "housenumber": "353",
            "postalcode": "02247-000",
            "neighbourhood": "Parada Inglesa",
            "confidence": 0.9,
        },
        endereco,
    )
    homonimo = pontuar_candidato(
        {
            "label": "Rua Borges Ladário, São Paulo",
            "street": "Rua Borges Ladário",
            "confidence": 0.9,
        },
        endereco,
    )
    assert exato > homonimo


def test_resolver_escolhe_automaticamente_quando_adequacao_e_clara():
    texto = "R. Voluntários da Pátria, 1000 - Santana, São Paulo - SP, 02011-000"
    melhor = Local(texto, "R. Voluntários da Pátria, 1000 — Santana", LAT, LON, 0.95, adequacao=90)
    outro = Local(texto, "R. Voluntários da Pátria — Perus", LAT, LON, 0.85, adequacao=30)
    resolucao = resolver_geocodificacao(texto, [melhor, outro])

    assert resolucao.automatico is True
    assert resolucao.local == melhor
    assert resolucao.opcoes == ()


def test_resolver_obriga_escolha_quando_empata():
    texto = "Rua Borges, 353 - Parada Inglesa, São Paulo - SP, 02247-000"
    um = Local(texto, "Rua Borges, São Paulo", LAT, LON, 0.9, adequacao=55)
    dois = Local(texto, "Rua Borges Ladário, São Paulo", LAT, LON, 0.88, adequacao=50)
    resolucao = resolver_geocodificacao(texto, [um, dois])

    assert resolucao.automatico is False
    assert resolucao.local is None
    assert len(resolucao.opcoes) == 2


def test_cep_ja_presente_nao_e_duplicado():
    texto = "Rua São João, 100, 01035-000"
    assert montar_consulta(texto, "01035-000") == texto


def test_sem_cep_o_texto_passa_limpo():
    assert montar_consulta("  Rua São João, 100  ", None) == "Rua São João, 100"


def feature_pelias(
    label: str,
    locality: str | None,
    confianca: float,
    lon=LON,
    lat=LAT,
    *,
    layer: str | None = None,
    street: str | None = None,
    housenumber: str | None = None,
) -> dict:
    props = {"label": label, "locality": locality, "confidence": confianca}
    if layer is not None:
        props["layer"] = layer
    if street is not None:
        props["street"] = street
    if housenumber is not None:
        props["housenumber"] = housenumber
    return {
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": props,
    }


def test_candidato_de_outro_municipio_e_descartado():
    """Homônimo de rua em Guarulhos não pode virar decisão em São Paulo."""
    assert local_de_feature(feature_pelias("R. das Flores, Guarulhos", "Guarulhos", 0.9), "x") is None


def test_candidato_de_sao_paulo_passa():
    local = local_de_feature(
        feature_pelias("R. das Flores, São Paulo", "São Paulo", 0.9, street="R. das Flores"),
        "x",
    )

    assert local is not None
    assert local.endereco_formatado == "R. das Flores, São Paulo"
    assert (local.lon, local.lat) == (LON, LAT)


def test_candidato_generico_de_cidade_e_descartado():
    """'São Paulo, Brazil' sem rua não serve para decidir elegibilidade."""
    assert local_de_feature(feature_pelias("São Paulo, Brazil", "São Paulo", 0.9, layer="locality"), "x") is None


def test_candidato_nome_curto_sem_rua_e_descartado():
    """Pelias devolvia 'Se, São Paulo, Brazil' para R. da Grota — isso não é endereço."""
    assert local_de_feature(feature_pelias("Se, São Paulo, Brazil", "São Paulo", 0.6, layer="neighbourhood", street=None), "x") is None


def test_local_de_nominatim_converte_resposta_osm():
    from core.nominatim_geo import local_de_nominatim

    endereco = EnderecoMaps(
        texto="R. da Grota, 483 - Vila Gustavo, São Paulo - SP, 02206-010",
        logradouro="R. da Grota",
        numero="483",
        bairro="Vila Gustavo",
        cidade="São Paulo",
        uf="SP",
        cep="02206-010",
    )
    resultado = {
        "display_name": "483, Rua da Grota, Vila Gustavo, Tucuruvi, São Paulo, Brasil",
        "lat": str(LAT),
        "lon": str(LON),
        "importance": 0.6,
        "type": "house",
        "class": "building",
        "address": {
            "house_number": "483",
            "road": "Rua da Grota",
            "suburb": "Vila Gustavo",
            "city": "São Paulo",
            "postcode": "02206-010",
        },
    }
    local = local_de_nominatim(resultado, endereco.texto, endereco)

    assert local is not None
    assert local.endereco_formatado.startswith("483, Rua da Grota")
    assert (local.lon, local.lat) == (LON, LAT)
    assert (local.adequacao or 0) >= 60


def test_consulta_nominatim_principal_prefere_numero_primeiro():
    from core.nominatim_geo import consulta_nominatim_principal

    endereco = EnderecoMaps(
        texto="Rua Borges, 353 - Parada Inglesa, São paulo, 02247000",
        logradouro="Rua Borges",
        numero="353",
        bairro="Parada Inglesa",
        cidade="São Paulo",
        uf="SP",
        cep="02247-000",
    )
    assert consulta_nominatim_principal(endereco) == (
        "353 Rua Borges, Parada Inglesa, São Paulo, SP, 02247-000"
    )


def test_geocodificar_cai_no_ors_quando_nominatim_e_photon_falham(monkeypatch):
    from core.nominatim_geo import NominatimRateLimited

    def nominatim_bloqueado(*args, **kwargs):
        raise NominatimRateLimited("HTTP 429")

    def photon_vazio(*args, **kwargs):
        return []

    def ors_fake(consulta, api_key, cep=None):
        return [
            {
                "geometry": {"coordinates": [LON, LAT]},
                "properties": {
                    "label": "353, Rua Borges, Parada Inglesa, São Paulo",
                    "locality": "São Paulo",
                    "street": "Rua Borges",
                    "housenumber": "353",
                    "postalcode": "02247-000",
                    "neighbourhood": "Parada Inglesa",
                    "confidence": 0.9,
                    "layer": "address",
                },
            }
        ]

    import core.endereco_maps as em
    import core.nominatim_geo as ng
    import core.photon_geo as pg

    monkeypatch.setattr(ng, "buscar_nominatim", nominatim_bloqueado)
    monkeypatch.setattr(pg, "buscar_photon", photon_vazio)
    monkeypatch.setattr(em, "_buscar_ors", ors_fake)

    candidatos = em.geocodificar(
        "Rua Borges, 353 - Parada Inglesa, São Paulo - SP, 02247-000",
        "chave-teste",
    )
    assert candidatos
    assert "Rua Borges" in candidatos[0].endereco_formatado


def test_geocodificar_usa_photon_quando_nominatim_limita(monkeypatch):
    from core.nominatim_geo import NominatimRateLimited

    def nominatim_bloqueado(*args, **kwargs):
        raise NominatimRateLimited("HTTP 429")

    def photon_fake(*args, **kwargs):
        return [
            {
                "geometry": {"coordinates": [LON, LAT]},
                "properties": {
                    "housenumber": "483",
                    "street": "Rua da Grota",
                    "district": "Vila Gustavo",
                    "city": "São Paulo",
                    "state": "São Paulo",
                    "country": "Brasil",
                    "postcode": "02206-010",
                    "osm_value": "house",
                },
            }
        ]

    def ors_vazio(*args, **kwargs):
        return []

    import core.endereco_maps as em
    import core.nominatim_geo as ng
    import core.photon_geo as pg

    monkeypatch.setattr(ng, "buscar_nominatim", nominatim_bloqueado)
    monkeypatch.setattr(pg, "buscar_photon", photon_fake)
    monkeypatch.setattr(em, "_buscar_ors", ors_vazio)

    candidatos = em.geocodificar(
        "R. da Grota, 483 - Vila Gustavo, São Paulo - SP, 02206-010",
        "chave-teste",
    )
    assert candidatos
    assert (candidatos[0].adequacao or 0) >= 60
    assert "Grota" in candidatos[0].endereco_formatado


def test_candidato_sem_municipio_passa():
    """Filtrar demais custaria endereços válidos; o rótulo ainda vai à conferência."""
    assert local_de_feature(
        feature_pelias("R. das Flores", None, 0.5, layer="street", street="R. das Flores"),
        "x",
    ) is not None


def candidato(label: str, confianca: float | None) -> Local:
    return Local("Rua São João", label, LAT, LON, confianca)


def test_scores_proximos_sao_sinalizados_como_ambiguos():
    """Em SP, 'Rua São João' sem CEP tem dezenas de respostas plausíveis."""
    ambiguos = candidatos_ambiguos(
        [candidato("R. São João, Centro", 0.90), candidato("R. São João, Perus", 0.85)]
    )

    assert [c.endereco_formatado for c in ambiguos] == ["R. São João, Perus"]


def test_score_distante_nao_e_ambiguo():
    ambiguos = candidatos_ambiguos(
        [candidato("R. São João, Centro", 0.95), candidato("R. São João, Perus", 0.40)]
    )

    assert ambiguos == []


def test_candidato_unico_nunca_e_ambiguo():
    assert candidatos_ambiguos([candidato("R. São João, Centro", 0.95)]) == []


# --------------------------------------------------------------------------- #
# Roteamento — leitura da resposta, sem rede
# --------------------------------------------------------------------------- #


def test_le_a_rota_da_resposta_do_ors():
    resposta = {
        "features": [
            {
                "geometry": {"type": "LineString", "coordinates": [[LON, LAT], [LON + 0.01, LAT]]},
                "properties": {"summary": {"distance": 1234.5, "duration": 900.0}},
            }
        ]
    }
    r = rota_de_geojson(resposta)

    assert r.distancia_m == 1234.5
    assert r.duracao_s == 900.0
    assert list(r.linha.coords) == [(LON, LAT), (LON + 0.01, LAT)]


def test_resposta_sem_rota_vira_erro_externo():
    """ORS sem rota é 'não sei responder', não 'sem direito'."""
    with pytest.raises(ErroExterno):
        rota_de_geojson({"features": []})


def test_rota_reta_mede_em_metros():
    casa = Local("casa", "casa", LAT, LON, None)
    escola = Local("escola", "escola", LAT - 1000 * METRO_EM_GRAUS_LAT, LON, None)

    assert math.isclose(rota_reta(casa, escola).distancia_m, 1000, rel_tol=0.01)
