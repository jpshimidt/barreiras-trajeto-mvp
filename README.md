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

## Estado: Marco 1 concluído

`marco1.py` — script único de linha de comando, endereços fixos no código, três barreiras
num GeoJSON feito à mão. Imprime a decisão no terminal.

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

As geometrias atuais são **traçados aproximados feitos à mão** de três vias da Zona Norte
(Marginal Tietê, Av. Eng. Caetano Álvares, Av. Inajar de Souza), suficientes para validar
a lógica. O Marco 3 substitui o arquivo pela geometria real do OpenStreetMap, importada
via Overpass a partir da lista de ruas com a grafia usada. Cada feature carrega `origem`,
`osm_way_id` e `importado_em` para auditoria — hoje `origem: "manual"` e `osm_way_id: null`.

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

- Lista real das ruas-barreira, com a grafia usada no OSM — bloqueia o Marco 3.
- ID da relação OSM de São Paulo capital (descobrir via Nominatim, `admin_level=8`;
  a área do Overpass é `3600000000 + id`) — anotar aqui quando descoberto.
- Chave gratuita do OpenRouteService para rodar sem `--offline`.

## Próximos marcos

2. Quebrar em módulos `core/` e escrever `test_decisao.py` com geometrias sintéticas.
3. `scripts/importar_barreiras.py` (Overpass), com validação visual do GeoJSON.
4. Interface Streamlit.
5. Deploy no Streamlit Community Cloud **com acesso restrito por lista de e-mails**.
6. Validação com 15–20 casos conhecidos da Zona Norte.
