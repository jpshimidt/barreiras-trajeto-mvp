"""
API pública de geocodificação — reexporta `core.endereco_maps`.

A implementação vive em `endereco_maps.py` para evitar cache de módulo antigo
no deploy do Streamlit Cloud.
"""

from core.endereco_maps import (
    EXEMPLO_ENDERECO_MAPS,
    EnderecoMaps,
    Local,
    ResolucaoGeocode,
    candidatos_ambiguos,
    extrair_cep,
    geocodificar,
    local_de_feature,
    montar_consulta,
    parse_endereco_maps,
    pontuar_candidato,
    resolver_geocodificacao,
)

__all__ = [
    "EXEMPLO_ENDERECO_MAPS",
    "EnderecoMaps",
    "Local",
    "ResolucaoGeocode",
    "candidatos_ambiguos",
    "extrair_cep",
    "geocodificar",
    "local_de_feature",
    "montar_consulta",
    "parse_endereco_maps",
    "pontuar_candidato",
    "resolver_geocodificacao",
]
