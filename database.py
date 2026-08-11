import os
import logging
import re
from datetime import datetime
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


def _formatar_valor_campo(campo: str, valor: str) -> str:
    """Trata e converte os valores para os tipos esperados pelo PostgreSQL/Supabase."""
    txt = str(valor).strip()
    
    # Tratamento especial para datas de nascimento (converte DDMMAAAA ou DD/MM/AAAA para AAAA-MM-DD)
    if campo in ["data_nascimento", "dt_nascimento", "data_nac"]:
        nums = re.sub(r"\D", "", txt)
        
        # Formato DDMMAAAA (ex: 18091977 -> 1977-09-18)
        if len(nums) == 8:
            dia, mes, ano = nums[:2], nums[2:4], nums[4:]
            return f"{ano}-{mes}-{dia}"
            
        # Formato DD/MM/AAAA (ex: 18/09/1977 -> 1977-09-18)
        if "/" in txt:
            partes = txt.split("/")
            if len(partes) == 3:
                return f"{partes[2]}-{partes[1].zfill(2)}-{partes[0].zfill(2)}"
                
    return txt


def buscar_regulacoes_por_chat_id(chat_id):
    """Busca regulações no Supabase testando colunas individualmente sem interromper em caso de erro."""
    try:
        cid_int = int(chat_id)
        cid_str = str(chat_id)

        print(f"🔍 DEBUG SUPABASE: Buscando registros para chat_id (int: {cid_int}, str: '{cid_str}')", flush=True)

        colunas_possiveis = ["id_do_chat", "chat_id", "telegram_id"]

        for tabela in _obter_tabelas():
            for col in colunas_possiveis:
                for val in [cid_int, cid_str]:
                    try:
                        res = supabase.table(tabela).select("*").eq(col, val).execute()
                        if res and res.data and len(res.data) > 0:
                            print(f"📊 DEBUG SUPABASE: {len(res.data)} registros encontrados na tabela '{tabela}' (coluna '{col}').", flush=True)
                            return res.data
                    except Exception:
                        continue

        print("📊 DEBUG SUPABASE: Nenhum registro encontrado em nenhuma coluna/tabela.", flush=True)
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
        for col in ["numero_reg", "id", "id_regulacao", "numero_solicitacao"]:
            for val in [num_str, num_int] if num_int is not None else [num_str]:
                try:
                    res = supabase.table(tabela).select("*").eq(col, val).execute()
                    if res and res.data and len(res.data) > 0:
                        return res.data[0]
                except Exception:
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


async def atualizar_campo_regulacao(reg_id, campo: str, valor: str) -> bool:
    """Atualiza ou insere (UPSERT) o registro no Supabase com tratamento de tipos e logs detalhados."""
    try:
        if not reg_id or not campo:
            print("❌ [Supabase] ID ou Campo nulos recebidos para atualização.", flush=True)
            return False

        num_str = str(reg_id).strip()
        num_int = int(num_str) if num_str.isdigit() else None
        id_query = num_int if num_int is not None else num_str

        # Tratamento e conversão prévia do valor (ex: datas -> AAAA-MM-DD)
        valor_formatado = _formatar_valor_campo(campo, valor)

        print(f"🔄 [Supabase] Atualizando ID '{id_query}' | Campo '{campo}' -> '{valor_formatado}'", flush=True)

        payload = {campo: valor_formatado}

        # 1. Tenta o UPDATE direto na tabela testando variações de colunas e tipos
        colunas_id = ["numero_reg", "id", "id_regulacao"]
        valores_id = [id_query]
        if num_int is not None and num_str not in valores_id:
            valores_id.append(num_str)

        for c_id in colunas_id:
            for v_id in valores_id:
                try:
                    res = supabase.table(TABELA_SUPABASE).update(payload).eq(c_id, v_id).select().execute()
                    if res and res.data and len(res.data) > 0:
                        print(f"✅ [Supabase] Update realizado com sucesso por '{c_id}'!", flush=True)
                        return True
                except Exception:
                    continue

        # 2. Se a linha não existia para update, executa o UPSERT (cria a linha com os dados atualizados)
        print("⚠️ [Supabase] Registro não localizado para update. Executando UPSERT...", flush=True)
        dados_upsert = {
            "numero_reg": id_query,
            campo: valor_formatado
        }
        res_upsert = supabase.table(TABELA_SUPABASE).upsert(dados_upsert).select().execute()

        if res_upsert and res_upsert.data:
            print("✅ [Supabase] Registro criado e atualizado via UPSERT!", flush=True)
            return True

        print("❌ [Supabase] Nenhuma linha afetada na operação.", flush=True)
        return False

    except Exception as e:
        print(f"❌ [Supabase ERROR] Falha ao atualizar {campo}: {str(e)}", flush=True)
        return False


def deletar_regulacao_por_id(chat_id, numero_reg):
    """Deleta do Supabase a regulação correspondente ao chat_id e numero_reg."""
    try:
        cid_int = int(chat_id)
        num_str = str(numero_reg)

        for col in ["id_do_chat", "chat_id"]:
            try:
                resposta = (
                    supabase.table(TABELA_SUPABASE)
                    .delete()
                    .eq(col, cid_int)
                    .eq("numero_reg", num_str)
                    .execute()
                )
                if resposta and resposta.data:
                    return True
            except Exception:
                continue

        return True
    except Exception as e:
        print(f"❌ Erro ao deletar regulação {numero_reg}: {e}", flush=True)
        return False


async def excluir_regulacao_db(reg_id) -> bool:
    """Exclui uma regulação do Supabase buscando tanto pelo id quanto pelo numero_reg."""
    try:
        num_str = str(reg_id).strip()
        num_int = int(num_str) if num_str.isdigit() else None

        for col in ["numero_reg", "id"]:
            valores_busca = [num_str, num_int] if num_int is not None else [num_str]
            for val in valores_busca:
                try:
                    resposta = supabase.table(TABELA_SUPABASE).delete().eq(col, val).execute()
                    if resposta and resposta.data:
                        return True
                except Exception:
                    continue

        return False
    except Exception as e:
        print(f"❌ Erro ao excluir regulação do Supabase: {e}", flush=True)
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