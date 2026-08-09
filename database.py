def buscar_regulacoes_por_chat_id(chat_id):
    """Busca regulações no Supabase com diagnóstico de logs no Railway."""
    try:
        # Converter para inteiro e string para garantir a comparação
        cid_int = int(chat_id)
        cid_str = str(chat_id)

        print(f"🔍 DEBUG SUPABASE: Buscando registros para chat_id (int: {cid_int}, str: '{cid_str}')", flush=True)

        # 1. Tentativa como Inteiro/BigInt
        res = supabase.table("AlertaSUS_2.0").select("*").eq("chat_id", cid_int).execute()
        print(f"📊 DEBUG SUPABASE (Int): {len(res.data) if res.data else 0} registros encontrados.", flush=True)

        if res.data:
            return res.data

        # 2. Tentativa como String/Text
        res_str = supabase.table("AlertaSUS_2.0").select("*").eq("chat_id", cid_str).execute()
        print(f"📊 DEBUG SUPABASE (Text): {len(res_str.data) if res_str.data else 0} registros encontrados.", flush=True)

        if res_str.data:
            return res_str.data

        # 3. Tentativa sem filtro (Carrega 5 linhas para checar o tipo retornado do BD)
        res_all = supabase.table("AlertaSUS_2.0").select("chat_id, numero_reg, nome_paciente").limit(5).execute()
        print(f"⚠️ DEBUG SUPABASE (Amostra de dados da tabela): {res_all.data}", flush=True)

        return []

    except Exception as e:
        print(f"❌ ERRO CRÍTICO SUPABASE: {e}", flush=True)
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