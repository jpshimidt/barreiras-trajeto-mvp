# Elegibilidade a transporte escolar — São Paulo capital

Protótipo que decide se uma criança tem direito a transporte escolar: se o menor
caminho a pé entre a casa e a escola encosta em alguma rua cadastrada como barreira,
tem direito.

| Responsável escolheu a escola | Caminho a pé toca barreira | Resultado |
|---|---|---|
| Sim | irrelevante | **Sem direito** |
| Não | Sim | **Com direito** |
| Não | Não | **Sem direito** |

Não existe critério de distância. Andar ao longo da barreira conta igual a atravessá-la.

**Nada é persistido.** A aplicação processa endereços residenciais de crianças: sem log,
sem histórico, sem analytics.

## Estado: Marcos 1, 2 e 3 concluídos

A lógica mora em `core/`; `marco1.py` é a casca de linha de comando com os endereços fixos.

```
core/
├── geo.py         projeção UTM e buffer métrico
├── barreiras.py   carga do GeoJSON e interseção rota x buffer
├── geocode.py     endereço -> coordenada, com filtro de município e detecção de ambiguidade
├── routing.py     coordenadas -> rota a pé
├── decisao.py     a tabela de decisão, e nada além dela
├── ors.py         chave da API e tradução de erro HTTP
└── erros.py       ErroExterno
scripts/
└── importar_barreiras.py  Overpass -> dados/barreiras.geojson (roda offline)
testes/
├── test_decisao.py       a regra e a geometria
├── test_importador.py    conversão Overpass -> GeoJSON
├── conftest.py           bloqueia socket na suíte inteira
└── casos_conhecidos.csv  só o cabeçalho — aguarda os casos reais (Marco 6)
```

`decisao.py` não sabe o que é HTTP e `geo.py` não sabe o que é transporte escolar: a
regra pode ser testada sem chave de API e sem rede.

### Testes

```bash
python -m pytest          # 59 testes, ~0,3 s
```

Use `python -m pytest`, não `pytest` direto — em máquina onde o `pytest` do PATH vive num
ambiente isolado, ele não enxerga o shapely instalado no projeto.

Um `conftest.py` derruba `socket` na suíte inteira: teste que tentar chamar a API falha
com mensagem explícita. Sem isso, a suíte passaria a depender da cota do ORS e deixaria
de dizer se a *regra* está certa.

O que os testes cobrem:

- as três linhas da tabela de decisão, incluindo a precedência da flag "escolheu a escola";
- o corte do buffer em 5 m (4,9 m toca, 5,1 m não toca);
- rota **paralela** à barreira a 3 m — caminhar ao longo conta igual a atravessar;
- regressão do buffer em graus: buffer projetado tem área `2rL + πr²`, o em graus tem
  mais de 1.000 km de largura;
- avenida fragmentada em vários ways aparece uma vez só no motivo;
- cadastro de barreiras vazio estoura erro em vez de virar "sem direito" silencioso;
- candidato de geocodificação em outro município é descartado; scores próximos viram aviso
  de ambiguidade;
- resposta do ORS sem rota vira `ErroExterno` — "não sei responder", não "sem direito".

## Linha de comando

`marco1.py` — endereços fixos no código, três barreiras num GeoJSON feito à mão.
Imprime a decisão no terminal.

```bash
pip install -r requirements.txt
export ORS_API_KEY="sua-chave"      # criar em openrouteservice.org

python marco1.py                    # caso 1
python marco1.py --caso 2
python marco1.py --todos            # os três casos
python marco1.py --buffer 10        # experimentar outro buffer
```

A chave também é lida de `.streamlit/secrets.toml` (`ORS_API_KEY = "..."`), que está no
`.gitignore` e não deve ser versionado.

### Modo offline

```bash
python marco1.py --todos --offline
```

Não chama o OpenRouteService: usa coordenadas fixas e uma **linha reta** entre casa e
escola. Serve para validar projeção UTM, buffer métrico e interseção sem chave de API —
a linha reta não é o menor caminho a pé, então o resultado não vale como decisão real.

Código de saída: `0` todos os casos bateram, `1` algum divergiu, `2` erro externo
(ORS fora do ar, cota estourada, endereço não encontrado).

### Casos fixos

| # | Trajeto | Escolheu a escola | Esperado |
|---|---|---|---|
| 1 | Santana → Bom Retiro (atravessa a Marginal Tietê) | não | com direito |
| 2 | Santana → Santana (percurso curto no mesmo distrito) | não | sem direito |
| 3 | Mesmo trajeto do caso 1 | sim | sem direito |

Os três cobrem as três linhas da tabela de decisão.

## Barreiras

`dados/barreiras.geojson` — FeatureCollection em EPSG:4326.

> **As geometrias em uso hoje são traçados aproximados feitos à mão** de três vias da Zona
> Norte, suficientes para validar a lógica. Rode o importador para substituí-las pela
> geometria real do OpenStreetMap.

Cada feature carrega `origem`, `osm_way_id` e `importado_em` para auditoria: seis meses
depois é preciso saber qual cadastro valia quando a decisão foi tomada. No arquivo à mão
esses campos são `"manual"` e `null`; o importador preenche de verdade.

### Importador (`scripts/importar_barreiras.py`)

Roda **offline**, quando o cadastro muda — nunca no runtime do app.

```bash
python scripts/importar_barreiras.py --ruas dados/ruas_barreira.txt --dry-run  # só mostra a consulta
python scripts/importar_barreiras.py --ruas dados/ruas_barreira.txt            # importa de verdade
python scripts/importar_barreiras.py --ruas dados/ruas_barreira.txt --regex    # quando o nome exato não retorna nada
```

A lista de ruas fica em `dados/ruas_barreira.txt`, uma por linha. **A lista atual é
provisória** — seis ruas de fronteira da Zona Norte escolhidas só para exercitar o
importador, com grafia por confirmar.

O ID da relação OSM de São Paulo é descoberto sozinho via Nominatim, conferindo que o
resultado é `relation` com `admin_level=8` (município, não o estado homônimo). O script
imprime o número na primeira execução — **anote aqui**, é constante:

```
Relação OSM de São Paulo capital: ______  (área do Overpass = 3600000000 + relação)
```

Depois use `--relacao-id <número>` para pular a consulta ao Nominatim.

**A consulta não abre mão de dois detalhes:** o filtro `["highway"]`, sem o qual casariam
trilhos, cursos d'água e limites administrativos; e `out geom;`, que devolve as coordenadas
inline. A área vem do ID da relação, nunca de `area["name"="São Paulo"]` — esse nome casa
o estado e o município ao mesmo tempo.

### Validação depois de importar — obrigatória

O script já denuncia sozinho os dois sintomas de grafia errada:

- rua pedida que voltou **zero** ways → aviso em `stderr`, e o nome provavelmente está
  escrito diferente no OSM (`Marginal Tietê` × `Marginal Tiete` × `Via Marginal do Rio
  Tietê`). Tente de novo com `--regex` e um pedaço distintivo do nome;
- rua com **um ou dois** ways → provavelmente um trecho solto. Uma avenida de verdade em
  São Paulo vem fragmentada em dezenas ou centenas de ways, um por trecho entre cruzamentos,
  por sentido de pista e por faixa marginal. Isso é normal e não atrapalha a interseção;
  só espere um arquivo grande.

Nada disso substitui **abrir o GeoJSON no geojson.io e olhar**. Uma barreira que não foi
importada gera silenciosamente um "sem direito" errado, e ninguém vai perceber.

## Detalhes que importam

**Buffer em metros, não em graus.** `.buffer(5)` em geometria WGS84 gera um buffer de
5 graus — centenas de quilômetros. `marco1.py` projeta rota e barreiras para a zona UTM
local (São Paulo cai em EPSG:32723) antes de aplicar o buffer. Verificado: uma rota
paralela a 4,9 m toca a barreira, a 5,1 m não toca.

**Geocodificação ambígua.** São Paulo tem 96 distritos e milhares de nomes de rua repetidos
entre eles. O CEP entra no texto enviado ao geocodificador, o endereço formatado devolvido
é impresso para conferência, e quando dois candidatos têm score próximo (margem de 0,10) o
script exibe a lista em vez de escolher em silêncio.

## Pendências

- **Rodar o importador numa máquina com acesso ao OSM.** O importador nunca foi executado
  de verdade: o ambiente onde foi escrito bloqueia `nominatim.openstreetmap.org` e
  `overpass-api.de`. A conversão Overpass → GeoJSON está coberta por testes com resposta
  montada à mão, mas a consulta em si só se prova rodando. Até lá, `dados/barreiras.geojson`
  continua sendo o arquivo feito à mão.
- Lista real das ruas-barreira, com a grafia usada no OSM (a de hoje é provisória).
- ID da relação OSM de São Paulo capital — anotar acima na primeira execução.
- Chave gratuita do OpenRouteService para rodar sem `--offline`.

## Deploy (Streamlit Community Cloud)

| Campo do painel | Valor |
|---|---|
| Repository | `jpshimidt/barreiras-trajeto-mvp` |
| Branch | `claude/school-transport-sp-app-q14h54` |
| Main file path | `app.py` — **ainda não existe, é o Marco 4** |

A chave vai em Settings → Secrets como `ORS_API_KEY = "..."`, nunca no repositório.

**Antes de compartilhar o link:** Settings → Sharing, trocar de público para a lista de
e-mails autorizados. A página recebe endereços residenciais de crianças e a escola que
elas frequentam; um app público no `streamlit.app` é indexável e adivinhável pelo nome.
Quem for testar precisa de conta Google (ou do provedor aceito) para autenticar — avise
antes de mandar o link, senão a pessoa bate numa tela de login sem entender o motivo.

## Próximos marcos

4. Interface Streamlit (`app.py` na raiz — é o *main file path* do Streamlit Cloud).
5. Deploy no Streamlit Community Cloud **com acesso restrito por lista de e-mails**.
6. Validação com 15–20 casos conhecidos da Zona Norte.
