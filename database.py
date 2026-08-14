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

# Inicialização e Validação Estrita das Credenciais do Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    logger.critical("❌ CRÍTICO: 'SUPABASE_URL' ou 'SUPABASE_KEY' não configuradas no ambiente! O banco de dados não funcionará.")
    supabase = None
else:
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("✅ Supabase inicializado com sucesso no database.py.")
    except Exception as e:
        logger.error(f"⚠️ Erro ao criar cliente Supabase: {e}")
        supabase = None


def _obter_tabelas():
    return [TABELA_SUPABASE, "principal"]


def _formatar_valor_campo(campo: str, valor: str) -> str:
    txt = str(valor).strip()
    if campo in ["data_nascimento", "dt_nascimento", "data_nac"]:
        return formatar_data(txt)
    return txt


def buscar_regulacoes_por_chat_id(chat_id):
    if not supabase:
        return []
    try:
        cid_int = int(chat_id) if str(chat_id).isdigit() else chat_id
        cid_str = str(chat_id)

        colunas_possiveis = ["chat_id", "id_do_chat", "telegram_id"]

        for tabela in _obter_tabelas():
            for col in colunas_possiveis:
                for val in [cid_str, cid_int]:
                    try:
                        res = supabase.table(tabela).select("*").eq(col, val).execute()
                        if res and res.data and len(res.data) > 0:
                            return res.data
                    except Exception:
                        continue
        return []
    except Exception as e:
        logger.error(f"❌ Erro ao buscar regulações por chat_id: {e}")
        return []


def obter_regulacao_por_numero(numero_reg: str):
    if not supabase or not numero_reg:
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
    return obter_regulacao_por_numero(id_reg)


async def salvar_regulacao(dados: dict) -> bool:
    if not supabase:
        return False
    try:
        payload = {
            "chat_id": str(dados.get("chat_id") or dados.get("id_do_chat")),
            "numero_reg": dados.get("numero_reg") or dados.get("regulacao"),
            "nome_paciente": dados.get("nome_paciente") or dados.get("nome"),
            "status_anterior": dados.get("status_anterior") or "PENDENTE",
            "data_nascimento": dados.get("data_nascimento") or dados.get("nascimento"),
            "celular": dados.get("celular"),
            "numero_sus": dados.get("numero_sus") or dados.get("sus"),
            "cbo": dados.get("cbo"),
            "procedimento": dados.get("procedimento")
        }

        resposta = supabase.table(TABELA_SUPABASE).insert(payload).execute()
        
        if resposta.data:
            logger.info("Regulação salva com sucesso no Supabase!")
            return True
        return False

    except Exception as e:
        logger.error(f"❌ Erro ao salvar regulação: {e}")
        return False


def atualizar_campo_regulacao(reg_id, campo, novo_valor):
    if not supabase:
        return False
    try:
        reg_id_str = str(reg_id).strip()

        if campo == "status_atual":
            campo = "status_anterior"

        novo_valor_formatado = _formatar_valor_campo(campo, novo_valor)

        res = supabase.table(TABELA_SUPABASE).update({campo: novo_valor_formatado}).eq("id", reg_id_str).execute()
        if res.data and len(res.data) > 0:
            return True

        res_alt = supabase.table(TABELA_SUPABASE).update({campo: novo_valor_formatado}).eq("numero_reg", reg_id_str).execute()
        if res_alt.data and len(res_alt.data) > 0:
            return True

        return False
    except Exception as e:
        logger.error(f"Erro ao executar UPDATE no Supabase: {e}")
        return False


def deletar_regulacao_por_id(chat_id, numero_reg):
    if not supabase:
        return False
    try:
        cid_int = int(chat_id) if str(chat_id).isdigit() else chat_id
        cid_str = str(chat_id)
        num_str = str(numero_reg)

        for col in ["chat_id", "id_do_chat"]:
            for val in [cid_str, cid_int]:
                try:
                    resposta = (
                        supabase.table(TABELA_SUPABASE)
                        .delete()
                        .eq(col, val)
                        .eq("numero_reg", num_str)
                        .execute()
                    )
                    if resposta and resposta.data:
                        return True
                except Exception:
                    continue
        return True
    except Exception as e:
        logger.error(f"❌ Erro ao deletar regulação {numero_reg}: {e}")
        return False


async def excluir_regulacao_db(reg_id) -> bool:
    if not supabase:
        return False
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
        logger.error(f"❌ Erro ao excluir regulação do Supabase: {e}")
        return False


from datetime import datetime, timezone, timedelta

async def registrar_consentimento_lgpd(user_id, aceito: bool = True) -> bool:
    if not supabase:
        return False
    try:
        # Define o fuso horário do Brasil (UTC-3)
        fuso_brasil = timezone(timedelta(hours=-3))
        agora_brasil = datetime.now(fuso_brasil).isoformat()

        dados = {
            "chat_id": str(user_id),
            "termo_aceito": aceito,
            "data_aceito": agora_brasil  # Garante o registro na hora local
        }
        
        # Como o 'chat_id' é Unique agora, o upsert funciona perfeitamente sem duplicar
        supabase.table("lgpd_consentimentos").upsert(dados, on_conflict="chat_id").execute()
        logger.info(f"Consentimento LGPD registrado/atualizado para o chat_id {user_id}")
        return True
    except Exception as e:
        logger.error(f"⚠️ Erro ao registrar LGPD: {e}")
        return False


async def buscar_todas_regulacoes_ativas():
    if not supabase:
        return []
    try:
        res = supabase.table(TABELA_SUPABASE).select("*").neq("ativo", False).execute()
        return res.data if res and res.data else []
    except Exception:
        try:
            res = supabase.table(TABELA_SUPABASE).select("*").execute()
            return res.data if res and res.data else []
        except Exception as e:
            logger.error(f"❌ Erro na varredura geral Supabase: {e}")
            return []


def desativar_regulacoes_por_chat_id(chat_id):
    """Marca como inativas as regulações de um chat_id que bloqueou o bot."""
    if not supabase:
        return False
    try:
        cid_str = str(chat_id)
        cid_int = int(chat_id) if cid_str.isdigit() else chat_id

        for col in ["chat_id", "id_do_chat"]:
            for val in [cid_str, cid_int]:
                try:
                    supabase.table(TABELA_SUPABASE).update({"ativo": False}).eq(col, val).execute()
                except Exception:
                    continue
        logger.info(f"🚫 Regulações do chat_id {chat_id} marcadas como inativas por bloqueio do usuário.")
        return True
    except Exception as e:
        logger.error(f"Erro ao desativar regulações do chat_id {chat_id}: {e}")
        return False