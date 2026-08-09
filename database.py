import os
from supabase import create_client, Client

# Inicialização do cliente Supabase (garante que a variável 'supabase' exista)
try:
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print(f"⚠️ Alerta na inicialização do Supabase no database.py: {e}", flush=True)


def buscar_regulacoes_por_chat_id(chat_id):
    """Busca regulações no Supabase com diagnóstico de logs e suporte a int/str."""
    try:
        cid_int = int(chat_id)
        cid_str = str(chat_id)

        print(f"🔍 DEBUG SUPABASE: Buscando registros para chat_id (int: {cid_int}, str: '{cid_str}')", flush=True)

        # 1. Tentativa com chat_id como Inteiro / BigInt
        res = supabase.table("AlertaSUS_2.0").select("*").eq("chat_id", cid_int).execute()
        print(f"📊 DEBUG SUPABASE (Int): {len(res.data) if res and res.data else 0} registros encontrados.", flush=True)

        if res and res.data:
            return res.data

        # 2. Tentativa com chat_id como String / Text
        res_str = supabase.table("AlertaSUS_2.0").select("*").eq("chat_id", cid_str).execute()
        print(f"📊 DEBUG SUPABASE (Text): {len(res_str.data) if res_str and res_str.data else 0} registros encontrados.", flush=True)

        if res_str and res_str.data:
            return res_str.data

        return []

    except Exception as e:
        print(f"❌ ERRO CRÍTICO SUPABASE: {e}", flush=True)
        return []


def deletar_regulacao_por_id(chat_id, numero_reg):
    """
    Deleta do Supabase a regulação correspondente ao chat_id e numero_reg.
    """
    try:
        cid_int = int(chat_id)
        num_str = str(numero_reg)

        # Deleta no Supabase comparando o chat_id (int) e o numero_reg (text)
        resposta = (
            supabase.table("AlertaSUS_2.0")
            .delete()
            .eq("chat_id", cid_int)
            .eq("numero_reg", num_str)
            .execute()
        )
        print(f"✅ Regulação {num_str} deletada com sucesso para o chat_id {cid_int}.", flush=True)
        return True
    except Exception as e:
        print(f"❌ Erro ao deletar regulação {numero_reg}: {e}", flush=True)
        return False