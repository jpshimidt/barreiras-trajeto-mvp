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

## Estado

Marcos 1 a 4 entregues. Os Marcos 5 (deploy) e 6 (validação) dependem de ações suas —
veja **Pendências**.

A lógica mora em `core/`. Nem `app.py` nem `marco1.py` decidem coisa alguma: são cascas.

```
app.py             interface Streamlit (main file path do Streamlit Cloud)
marco1.py          a mesma regra em linha de comando, com endereços fixos
core/
├── geo.py         projeção UTM e buffer métrico
├── barreiras.py   carga do GeoJSON e interseção rota x buffer
├── geocode.py     endereço -> coordenada, com filtro de município e detecção de ambiguidade
├── routing.py     coordenadas -> rota a pé
├── decisao.py     a tabela de decisão, e nada além dela
├── ors.py         chave da API e tradução de erro HTTP
└── erros.py       ErroExterno
scripts/
├── importar_barreiras.py      Overpass -> dados/barreiras.geojson (roda offline)
└── rodar_casos_conhecidos.py  valida o CSV de casos contra o pipeline real
testes/
├── test_decisao.py         a regra e a geometria
├── test_importador.py      conversão Overpass -> GeoJSON
├── test_app.py             a interface, via AppTest, com serviços dublados
├── test_casos_conhecidos.py  leitura do CSV e o laço do validador
├── conftest.py             bloqueia socket na suíte inteira
└── casos_conhecidos.csv    só o cabeçalho — aguarda os casos reais (Marco 6)
```

`decisao.py` não sabe o que é HTTP e `geo.py` não sabe o que é transporte escolar: a
regra pode ser testada sem chave de API e sem rede.

### Testes

```bash
python -m pytest          # 92 testes, ~2 s
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
- resposta do ORS sem rota vira `ErroExterno` — "não sei responder", não "sem direito";
- a interface inteira, com geocodificação e roteamento dublados: botão desabilitado sem os
  dois endereços, endereço formatado exibido, empate de score virando escolha do usuário,
  falha do ORS que **não** aparece como "sem direito", e a flag da escola decidindo sem
  gastar chamada de rota;
- o laço do validador de casos conhecidos, incluindo o código de saída em divergência.

## Interface

```bash
pip install -r requirements.txt
export ORS_API_KEY="sua-chave"
streamlit run app.py
```

O fluxo é o do plano: endereço da casa → endereço formatado de volta para conferência →
endereço da escola → conferência → checkbox "a responsável escolheu esta escola" →
Calcular → resultado destacado, motivo, distância e mapa (rota em azul, barreiras em
vermelho com traço grosso nas tocadas, pins em A e B).

Três decisões da interface que valem registro:

- **Geocodificação e roteamento não são cacheados.** `st.cache_data` guardaria endereços
  residenciais de crianças na memória do servidor, compartilhados entre sessões — o oposto
  do que este protótipo promete. Só o cadastro de barreiras (público, versionado) usa
  `st.cache_resource`. São ~10 consultas por dia; não há desempenho a resolver.
- **O mapa desenha só as barreiras próximas da rota.** O cadastro real tem megabytes;
  jogar tudo no Folium trava o navegador.
- **Com a flag marcada, a rota nem é pedida.** O resultado já está definido, e chamar o
  roteador seria queimar cota para uma resposta que não muda.

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
Relação OSM de São Paulo capital: 298285  (área do Overpass = 3600298285)
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

## Validação com casos reais (Marco 6)

```bash
export ORS_API_KEY="sua-chave"
python scripts/rodar_casos_conhecidos.py
```

Lê `testes/casos_conhecidos.csv`, roda cada caso pelo pipeline real e compara com a
resposta que já se sabe correta. Imprime tudo no terminal e **não grava nada** — o arquivo
de entrada tem endereços residenciais de crianças. Sai com `0` se todos baterem, `1` em
divergência, `2` em erro externo.

O CSV está **vazio de casos**, só com o cabeçalho: precisa de 15 a 20 casos da Zona Norte
cuja resposta correta já se saiba, metade com direito e metade sem. Caso cuja resposta
ninguém consegue conferir não valida nada. Inclua o CEP desde o início — sem ele, uma falha
de geocodificação vai parecer falha da regra de negócio.

**Não ajuste o buffer antes de ter esses casos rodando.** Em divergência, investigue: o
endereço formatado está certo? a rua-barreira do caso está no cadastro com a grafia do OSM?
A causa quase nunca é o buffer. O script imprime esse lembrete sozinho quando diverge.

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

Nada aqui é código faltando: são coisas que dependem de rede, de dado real ou de acesso a
painel, e por isso não puderam ser feitas em ambiente de desenvolvimento.

| O que falta | Bloqueia | Por quê |
|---|---|---|
| Rodar o importador numa máquina com acesso ao OSM | cadastro real de barreiras | O ambiente onde foi escrito bloqueia `nominatim.openstreetmap.org` e `overpass-api.de`. A conversão Overpass → GeoJSON tem testes com resposta montada à mão, mas a consulta em si só se prova rodando. Até lá vale o GeoJSON feito à mão. |
| Lista real das ruas-barreira, com a grafia do OSM | precisão das decisões | A lista de hoje são seis ruas de fronteira escolhidas para teste. |
| ID da relação OSM de São Paulo capital | nada — descoberto sozinho | Anotar acima na primeira execução do importador, para pular o Nominatim depois. |
| Chave do OpenRouteService | rodar fora do `--offline` | Nunca foi colada aqui, de propósito. |
| Uma execução real ponta a ponta | confiança na decisão | Nenhuma consulta de verdade ao ORS foi feita: geocodificação e roteamento estão cobertos por dublês, nunca pelo serviço. |
| 15–20 casos conhecidos da Zona Norte | Marco 6 | Só quem conhece a região consegue dizer qual é a resposta certa. |
| Deploy e restrição por e-mail | Marco 5 | Feito no painel do Streamlit Cloud, não pelo repositório. |

## Deploy (Streamlit Community Cloud)

| Campo do painel | Valor |
|---|---|
| Repository | `jpshimidt/barreiras-trajeto-mvp` |
| Branch | `claude/school-transport-sp-app-q14h54` |
| Main file path | `app.py` |

Passo a passo:

1. `.streamlit/secrets.toml` já está no `.gitignore` — confira antes do push.
2. Em share.streamlit.io, conectar o GitHub e apontar para o repositório, branch e
   main file path da tabela acima.
3. Colar a chave em Settings → Secrets: `ORS_API_KEY = "..."`. Nunca no repositório.
4. **Restringir o acesso por e-mail** (abaixo) — antes de mandar o link para alguém.
5. Aguardar o build; o `requirements.txt` é instalado sozinho.
6. Testar de ponta a ponta pelo link, de outro dispositivo.

Cada push na branch configurada redeploya sozinho.

`.streamlit/config.toml` já vai versionado com `gatherUsageStats = false`: sem telemetria,
coerente com a promessa de não persistir nada.

**Antes de compartilhar o link:** Settings → Sharing, trocar de público para a lista de
e-mails autorizados. A página recebe endereços residenciais de crianças e a escola que
elas frequentam; um app público no `streamlit.app` é indexável e adivinhável pelo nome.
Quem for testar precisa de conta Google (ou do provedor aceito) para autenticar — avise
antes de mandar o link, senão a pessoa bate numa tela de login sem entender o motivo.

## Fora de escopo na v1

Registrado para não virar discussão no meio da implementação: processamento em lote,
banco de dados, cadastro de barreiras pela interface, autenticação própria, lista fixa de
escolas, outros municípios, barreiras que não sejam ruas, PDF de parecer, histórico de
consultas e cálculo da rota alternativa que evita barreiras (não altera a decisão).

Se algum virar necessidade, o ponto natural de evolução é trocar o GeoJSON em arquivo por
Postgres com PostGIS, onde `ST_Intersects` faz a verificação no banco.
