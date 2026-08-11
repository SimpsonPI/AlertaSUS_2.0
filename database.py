import os
import logging
from supabase import create_client, Client

logger = logging.getLogger(__name__)

# Nome padrão da tabela no Supabase
TABELA_SUPABASE = "AlertaSUS_2.0"

# Inicialização do cliente Supabase
try:
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print(f"⚠️ Alerta na inicialização do Supabase no database.py: {e}", flush=True)


def _obter_tabelas():
    """Retorna as tabelas a serem pesquisadas por ordem de prioridade."""
    return [TABELA_SUPABASE, "principal"]


def buscar_regulacoes_por_chat_id(chat_id):
    """Busca regulações no Supabase com diagnóstico de logs e suporte a int/str."""
    try:
        cid_int = int(chat_id)
        cid_str = str(chat_id)

        print(f"🔍 DEBUG SUPABASE: Buscando registros para chat_id (int: {cid_int}, str: '{cid_str}')", flush=True)

        for tabela in _obter_tabelas():
            try:
                # 1. Tentativa com chat_id ou id_do_chat como Inteiro / BigInt
                res = supabase.table(tabela).select("*").eq("chat_id", cid_int).execute()
                if not res.data:
                    res = supabase.table(tabela).select("*").eq("id_do_chat", cid_int).execute()

                if res and res.data:
                    print(f"📊 DEBUG SUPABASE (Tabela {tabela}): {len(res.data)} registros encontrados.", flush=True)
                    return res.data

                # 2. Tentativa como String / Text
                res_str = supabase.table(tabela).select("*").eq("chat_id", cid_str).execute()
                if not res_str.data:
                    res_str = supabase.table(tabela).select("*").eq("id_do_chat", cid_str).execute()

                if res_str and res_str.data:
                    print(f"📊 DEBUG SUPABASE (Tabela {tabela} Text): {len(res_str.data)} registros encontrados.", flush=True)
                    return res_str.data
            except Exception as e_tab:
                continue

        return []

    except Exception as e:
        print(f"❌ ERRO CRÍTICO SUPABASE: {e}", flush=True)
        return []


def obter_regulacao_por_numero(numero_reg: str):
    """Busca os dados completos de uma regulação pelo ID/Número da Regulação no Supabase."""
    if not numero_reg:
        return None

    num_str = str(numero_reg).strip()
    num_int = int(num_str) if num_str.isdigit() else None

    for tabela in _obter_tabelas():
        try:
            # Busca como String na coluna numero_reg
            res = supabase.table(tabela).select("*").eq("numero_reg", num_str).execute()
            if res and res.data:
                return res.data[0]

            # Busca como Inteiro
            if num_int is not None:
                res_int = supabase.table(tabela).select("*").eq("numero_reg", num_int).execute()
                if res_int and res_int.data:
                    return res_int.data[0]

            # Busca pela chave primária 'id'
            res_id = supabase.table(tabela).select("*").eq("id", num_str).execute()
            if res_id and res_id.data:
                return res_id.data[0]

        except Exception as e:
            continue

    return None


def obter_regulacao_por_id(id_reg):
    """Alias para obter regulação por número ou chave primária."""
    return obter_regulacao_por_numero(id_reg)


async def salvar_regulacao(dados: dict) -> bool:
    """Insere uma nova regulação na tabela do Supabase."""
    try:
        resposta = supabase.table(TABELA_SUPABASE).insert(dados).execute()
        return bool(resposta.data)
    except Exception as e:
        print(f"❌ Erro ao salvar regulação no Supabase: {e}", flush=True)
        return False


async def atualizar_campo_regulacao(reg_id, campo: str, valor) -> bool:
    """Atualiza dinamicamente um campo específico no Supabase."""
    try:
        num_str = str(reg_id).strip()
        resposta = supabase.table(TABELA_SUPABASE).update({campo: valor}).eq("numero_reg", num_str).execute()
        
        if not resposta.data:
            # Fallback para ID primário
            resposta = supabase.table(TABELA_SUPABASE).update({campo: valor}).eq("id", num_str).execute()

        return bool(resposta.data)
    except Exception as e:
        print(f"❌ Erro ao atualizar campo {campo} no Supabase: {e}", flush=True)
        return False


def deletar_regulacao_por_id(chat_id, numero_reg):
    """Deleta do Supabase a regulação correspondente ao chat_id e numero_reg."""
    try:
        cid_int = int(chat_id)
        num_str = str(numero_reg)

        resposta = (
            supabase.table(TABELA_SUPABASE)
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


async def excluir_regulacao_db(reg_id) -> bool:
    """Exclui uma regulação apenas pelo número de regulação ou id no Supabase."""
    try:
        num_str = str(reg_id).strip()
        resposta = supabase.table(TABELA_SUPABASE).delete().eq("numero_reg", num_str).execute()
        if not resposta.data:
            resposta = supabase.table(TABELA_SUPABASE).delete().eq("id", num_str).execute()
        return bool(resposta.data)
    except Exception as e:
        print(f"❌ Erro ao excluir regulação {reg_id}: {e}", flush=True)
        return False


async def registrar_consentimento_lgpd(user_id, aceito: bool = True) -> bool:
    """Registra aceite do termo LGPD."""
    try:
        dados = {"chat_id": int(user_id), "lgpd_aceito": aceito}
        supabase.table("lgpd_consentimentos").upsert(dados).execute()
        return True
    except Exception as e:
        print(f"⚠️ Erro ao registrar LGPD: {e}", flush=True)
        return False


async def buscar_todas_regulacoes_ativas():
    """Busca todas as regulações cadastradas para a varredura automática."""
    try:
        res = supabase.table(TABELA_SUPABASE).select("*").execute()
        return res.data if res and res.data else []
    except Exception as e:
        print(f"❌ Erro na varredura geral Supabase: {e}", flush=True)
        return []