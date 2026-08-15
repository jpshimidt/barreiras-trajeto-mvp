"""Leitura do CSV de casos conhecidos. Sem rede: só o parser."""

from __future__ import annotations

import pytest

from scripts.rodar_casos_conhecidos import (
    COLUNAS,
    esperado_para_bool,
    ler_casos,
    rotulo,
    sim_ou_nao,
)

CABECALHO = ",".join(COLUNAS)


def escrever(tmp_path, *linhas):
    caminho = tmp_path / "casos.csv"
    caminho.write_text("\n".join([CABECALHO, *linhas]) + "\n", encoding="utf-8")
    return caminho


def test_le_um_caso_completo(tmp_path):
    caminho = escrever(
        tmp_path, '01,"R. X, 100",01234-567,"EM Fulano, R. Z, 50",04321-000,nao,com_direito'
    )
    (caso,) = ler_casos(caminho)

    assert caso.id == "01"
    assert caso.endereco_casa == "R. X, 100"
    assert caso.cep_casa == "01234-567"
    assert caso.escolheu_escola is False
    assert caso.esperado_tem_direito is True


def test_o_csv_versionado_tem_o_cabecalho_certo():
    """O arquivo do repositório está vazio de casos, mas o schema tem de valer."""
    assert ler_casos("testes/casos_conhecidos.csv") == []


def test_linha_em_branco_e_ignorada(tmp_path):
    caminho = escrever(tmp_path, '01,"R. X",,"R. Z",,nao,com_direito', ",,,,,,")

    assert len(ler_casos(caminho)) == 1


def test_coluna_faltando_e_denunciada(tmp_path):
    caminho = tmp_path / "casos.csv"
    caminho.write_text("id,endereco_casa\n01,R. X\n", encoding="utf-8")

    with pytest.raises(ValueError, match="faltam as colunas"):
        ler_casos(caminho)


@pytest.mark.parametrize("valor", ["sim", "SIM", "s", "true", "1"])
def test_variacoes_de_sim(valor):
    assert sim_ou_nao(valor, "x", 2) is True


@pytest.mark.parametrize("valor", ["nao", "não", "NÃO", "n", ""])
def test_variacoes_de_nao(valor):
    assert sim_ou_nao(valor, "x", 2) is False


def test_valor_invalido_aponta_a_linha():
    with pytest.raises(ValueError, match="linha 7"):
        sim_ou_nao("talvez", "escolheu_escola", 7)


@pytest.mark.parametrize(
    "valor, esperado",
    [("com_direito", True), ("COM DIREITO", True), ("sem_direito", False), ("sem direito", False)],
)
def test_resultado_esperado_aceita_as_grafias_usuais(valor, esperado):
    assert esperado_para_bool(valor, 2) is esperado


def test_resultado_esperado_invalido_e_recusado():
    """Typo aqui viraria 'sem_direito' silencioso e falsearia a validação inteira."""
    with pytest.raises(ValueError, match="com_direito"):
        esperado_para_bool("talvez", 2)


def test_rotulo():
    assert (rotulo(True), rotulo(False)) == ("COM DIREITO", "SEM DIREITO")


# --------------------------------------------------------------------------- #
# O laço inteiro, com os serviços externos dublados
# --------------------------------------------------------------------------- #


def test_laco_completo_confere_os_tres_tipos_de_caso(tmp_path, monkeypatch, capsys):
    """
    Prova o executor antes de gastar chamada de API: um caso com direito, um sem,
    e um resolvido só pela flag.
    """
    from shapely.geometry import LineString

    import scripts.rodar_casos_conhecidos as runner
    from core.geocode import Local
    from core.routing import Rota

    # Santana -> Bom Retiro atravessa a Marginal Tietê do cadastro; Santana -> Santana não.
    pontos = {
        "casa": Local("casa", "R. Voluntários da Pátria — Santana", -23.5100, -46.6280, 0.9),
        "longe": Local("longe", "Av. Rudge — Bom Retiro", -23.5265, -46.6440, 0.9),
        "perto": Local("perto", "R. Alfredo Pujol — Santana", -23.4995, -46.6260, 0.9),
    }
    monkeypatch.setattr(runner, "ler_api_key", lambda: "chave-de-teste")
    monkeypatch.setattr(runner, "geocodificar", lambda texto, k, cep=None: [pontos[texto]])
    monkeypatch.setattr(
        runner,
        "rota_a_pe",
        lambda o, d, k: Rota(LineString([(o.lon, o.lat), (d.lon, d.lat)]), 2451.0, 1800.0),
    )

    caminho = escrever(
        tmp_path,
        "01,casa,,longe,,nao,com_direito",
        "02,casa,,perto,,nao,sem_direito",
        "03,casa,,longe,,sim,sem_direito",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["runner", "--csv", str(caminho), "--geojson", "dados/barreiras.geojson", "--pausa", "0"],
    )

    assert runner.main() == 0
    assert "3/3 casos bateram com o esperado." in capsys.readouterr().out


def test_divergencia_devolve_codigo_de_erro(tmp_path, monkeypatch, capsys):
    """Divergência tem de ser visível no exit code, não só no texto."""
    from shapely.geometry import LineString

    import scripts.rodar_casos_conhecidos as runner
    from core.geocode import Local
    from core.routing import Rota

    casa = Local("casa", "R. Voluntários da Pátria", -23.5100, -46.6280, 0.9)
    monkeypatch.setattr(runner, "ler_api_key", lambda: "chave-de-teste")
    monkeypatch.setattr(runner, "geocodificar", lambda texto, k, cep=None: [casa])
    monkeypatch.setattr(
        runner,
        "rota_a_pe",
        lambda o, d, k: Rota(LineString([(-46.628, -23.510), (-46.626, -23.4995)]), 1181.0, 900.0),
    )

    caminho = escrever(tmp_path, "01,casa,,casa,,nao,com_direito")
    monkeypatch.setattr(
        "sys.argv",
        ["runner", "--csv", str(caminho), "--geojson", "dados/barreiras.geojson", "--pausa", "0"],
    )

    assert runner.main() == 1
    saida = capsys.readouterr().out
    assert "DIVERGIU" in saida
    assert "A causa quase nunca é o buffer." in saida
