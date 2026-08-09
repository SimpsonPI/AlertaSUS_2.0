def buscar_regulacoes_por_chat_id(chat_id):
    """
    Busca todas as regulações cadastradas para um determinado chat_id no Supabase.
    """
    try:
        # Consulta a tabela AlertaSUS_2.0 filtrando pelo chat_id
        resposta = (
            supabase.table("AlertaSUS_2.0")
            .select("*")
            .eq("chat_id", chat_id)
            .execute()
        )
        return resposta.data if resposta.data else []
    except Exception as e:
        print(f"Erro ao buscar regulações para o chat_id {chat_id}: {e}", flush=True)
        return []


def deletar_regulacao_por_id(chat_id, numero_reg):
    """
    Deleta do Supabase a regulação correspondente ao chat_id e numero_reg.
    """
    try:
        resposta = (
            supabase.table("AlertaSUS_2.0")
            .delete()
            .eq("chat_id", chat_id)
            .eq("numero_reg", str(numero_reg))
            .execute()
        )
        return True
    except Exception as e:
        print(f"Erro ao deletar regulação {numero_reg}: {e}", flush=True)
        return False