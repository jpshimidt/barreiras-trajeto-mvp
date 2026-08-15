# Política de segurança

Este repositório é **público**. Nunca commite segredos.

## Cadastro de barreiras (CRUD)

O disco do Streamlit Cloud é **efêmero** — gravações locais somem no redeploy.

**Solução adotada (custo zero):** GitHub Contents API grava `dados/barreiras.geojson` no repositório.

```toml
[github_barreiras]
token = "ghp_..."          # PAT com permissão de escrita no repo
repo = "usuario/barreiras-trajeto-mvp"
path = "dados/barreiras.geojson"
branch = "main"

[auth]
admin_usernames = ["admin"]  # só estes usuários acessam a página de CRUD
```

- Página **Gerenciar barreiras** (menu lateral, só para admins)
- Histórico e backup automáticos via Git
- Sem banco de dados externo

**Alternativa futura:** Supabase (PostgreSQL gratuito) se o CRUD via Git ficar limitado.

## O que NÃO vai no Git

- `.streamlit/secrets.toml` (já está no `.gitignore`)
- Chaves de API (ORS, Google), senhas, `cookie_key`
- Dados pessoais de consultas (o app não persiste endereços por design)

## Secrets no Streamlit Cloud

Configure em **Settings → Secrets**:

| Variável | Uso | Restrição recomendada no provedor |
|----------|-----|-----------------------------------|
| `ORS_API_KEY` | Rotas a pé (server) | Cota diária; só backend |
| `GOOGLE_MAPS_API_KEY` | Geocoding / Places server | IP ou sem referrer web |
| `GOOGLE_MAPS_JS_KEY` | Autocomplete no navegador | HTTP referrer `*.streamlit.app` |
| `github_barreiras.token` | CRUD do cadastro | PAT com escopo mínimo (`repo` ou Contents) |
| `[auth]` | Login | Senhas em **hash bcrypt** |

### Google Maps — duas chaves

A chave do widget JavaScript fica visível no navegador (DevTools). Por isso:

1. Crie **duas** chaves no Google Cloud Console.
2. `GOOGLE_MAPS_JS_KEY`: só Maps JavaScript API + Places, referrer `https://*.streamlit.app/*`.
3. `GOOGLE_MAPS_API_KEY`: Places (New) + Geocoding, **sem** expor no frontend.

## Autenticação

- Login é **obrigatório** — não há bypass em produção.
- `cookie_key` precisa ter ≥ 32 caracteres aleatórios; valores de exemplo bloqueiam o app.
- No Streamlit Cloud, senhas em texto puro nos Secrets são **recusadas**.

## Privacidade

- Endereços residenciais ficam só na sessão do navegador (`st.session_state`).
- Geocodificação e rotas **não** são cacheadas no servidor.

## Reportar vulnerabilidades

Abra um issue privado ou entre em contato com o mantenedor do repositório.
Não publique chaves ou credenciais em issues públicas.

## Dependências

Versões fixadas em `requirements.txt`. Atualize com revisão de changelog e `pytest`.
