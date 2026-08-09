def buscar_regulacoes_por_chat_id(chat_id):
    """Busca regulações no Supabase tratando o chat_id como int e str."""
    try:
        # Tenta buscar como int/BigInt
        resposta = supabase.table("AlertaSUS_2.0").select("*").eq("chat_id", int(chat_id)).execute()
        if resposta.data:
            return resposta.data
            
        # Se não achar, tenta buscar como texto/string
        resposta_str = supabase.table("AlertaSUS_2.0").select("*").eq("chat_id", str(chat_id)).execute()
        return resposta_str.data if resposta_str.data else []
    except Exception as e:
        print(f"Erro ao buscar regulações no Supabase: {e}", flush=True)
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