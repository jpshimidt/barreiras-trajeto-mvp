class ErroExterno(RuntimeError):
    """
    Falha que não é culpa da regra de negócio: ORS fora do ar, cota estourada,
    chave inválida, endereço não encontrado, arquivo de barreiras vazio.

    A interface trata isso como "não sei responder", nunca como "sem direito".
    """
