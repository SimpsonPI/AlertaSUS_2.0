import os
import logging
import re
from datetime import datetime
from supabase import create_client, Client

logger = logging.getLogger(__name__)

def formatar_data(texto: str) -> str:
    """Converte a data digitada para YYYY-MM-DD (padrão aceito pelo PostgreSQL/Supabase)."""
    nums = re.sub(r"\D", "", texto)
    if len(nums) == 8:
        dia, mes, ano = nums[:2], nums[2:4], nums[4:]
        return f"{ano}-{mes}-{dia}"
    elif "/" in texto:
        partes = texto.split("/")
        if len(partes) == 3 and len(partes[2]) == 4:
            return f"{partes[2]}-{partes[1].zfill(2)}-{partes[0].zfill(2)}"
    return texto

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
        return formatar_data(txt)
                
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


def atualizar_campo_regulacao(reg_id, campo, novo_valor):
    """
    Atualiza EXCLUSIVAMENTE um registro existente no Supabase.
    NUNCA cria linhas novas.
    """
    try:
        reg_id_str = str(reg_id).strip()
        novo_valor_formatado = _formatar_valor_campo(campo, novo_valor)
        logger.info(f"Fazendo UPDATE no Supabase -> Filtro Target ID: {reg_id_str} | Campo: {campo} | Valor: {novo_valor_formatado}")

        # 1. Tenta atualizar diretamente pela Chave Primária (coluna 'id')
        res = supabase.table(TABELA_SUPABASE).update({campo: novo_valor_formatado}).eq("id", reg_id_str).execute()

        # Se atualizou a linha com sucesso
        if res.data and len(res.data) > 0:
            logger.info("UPDATE realizado com sucesso por 'id'.")
            return True

        # 2. Se não achou por 'id', tenta atualizar pelo 'numero_reg'
        res_alt = supabase.table(TABELA_SUPABASE).update({campo: novo_valor_formatado}).eq("numero_reg", reg_id_str).execute()

        if res_alt.data and len(res_alt.data) > 0:
            logger.info("UPDATE realizado com sucesso por 'numero_reg'.")
            return True

        logger.error(f"Nenhum registro encontrado para atualizar com o ID/Numero: {reg_id_str}")
        return False

    except Exception as e:
        logger.error(f"Erro ao executar UPDATE no Supabase: {e}")
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