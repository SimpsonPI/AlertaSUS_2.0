import os
import logging
from datetime import datetime, timedelta, timezone
from supabase import create_client, Client

logger = logging.getLogger(__name__)

# --- INICIALIZAÇÃO DA CONEXÃO SUPABASE ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("As variáveis SUPABASE_URL e SUPABASE_KEY precisam estar configuradas no .env")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# --- AUXILIARES DE PLANOS ---

def calcular_dias_plano(tipo_plano: str) -> int:
    """Retorna a quantidade de dias de validade de um determinado plano."""
    plano_lower = tipo_plano.lower()
    if "degustacao" in plano_lower or "free" in plano_lower:
        return 7
    elif "mensal" in plano_lower or "essencial" in plano_lower:
        return 30
    elif "semestral" in plano_lower:
        return 180
    elif "anual" in plano_lower:
        return 365
    return 7


# --- REGRAS E GESTÃO DE PLANOS E ASSINATURAS ---

async def verificar_assinatura(user_id: int) -> dict | None:
    """Busca e retorna o registro completo da assinatura de um usuário no Supabase."""
    try:
        res = supabase.table("assinaturas").select("*").eq("chat_id", str(user_id)).execute()
        if res.data:
            return res.data[0]
        return None
    except Exception as e:
        logger.error(f"Erro ao obter dados de assinatura para o ID {user_id}: {e}")
        return None


def verificar_assinatura_ativa(user_id: int) -> bool:
    """Verifica se o usuário possui uma assinatura ativa no Supabase."""
    try:
        res = supabase.table("assinaturas").select("*").eq("chat_id", str(user_id)).execute()

        if not res.data:
            return False

        assinatura = res.data[0]

        if assinatura.get("status") != "active":
            return False

        if assinatura.get("tipo_plano") == "cortesia":
            return True

        data_vencimento_str = assinatura.get("data_vencimento")
        if not data_vencimento_str:
            return False

        vencimento = datetime.fromisoformat(data_vencimento_str.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) < vencimento
    except Exception as e:
        logger.error(f"Erro ao verificar assinatura ativa para o ID {user_id}: {e}")
        return False


def ativar_ou_atualizar_assinatura(telegram_id: int, tipo_plano: str):
    """Calcula as datas e realiza o upsert na tabela de assinaturas."""
    try:
        dias_validade = calcular_dias_plano(tipo_plano)
        agora = datetime.now(timezone.utc)
        vencimento = agora + timedelta(days=dias_validade)
        
        is_degustacao = "degustacao" in tipo_plano.lower() or "free" in tipo_plano.lower()

        dados = {
            "chat_id": str(telegram_id),
            "tipo_plano": tipo_plano,
            "status": "active",
            "data_inicio": agora.isoformat(),
            "data_vencimento": vencimento.isoformat()
        }

        # Se for um plano de degustação, trava a flag usou_degustacao como True
        if is_degustacao:
            dados["usou_degustacao"] = True

        resposta = supabase.table("assinaturas").upsert(dados, on_conflict="chat_id").execute()
        logger.info(f"Assinatura do plano '{tipo_plano}' atualizada para o chat_id: {telegram_id}")
        return resposta.data if resposta else True
    except Exception as e:
        logger.error(f"Erro ao ativar ou atualizar assinatura para o ID {telegram_id}: {e}")
        return None


async def iniciar_degustacao(chat_id: int) -> bool:
    """Ativa o período de degustação de 7 dias grátis gravando a trava permanente."""
    try:
        agora = datetime.now(timezone.utc)
        vencimento = agora + timedelta(days=7)
        
        dados = {
            "chat_id": str(chat_id),
            "tipo_plano": "degustacao",
            "status": "active",
            "usou_degustacao": True,
            "data_inicio": agora.isoformat(),
            "data_vencimento": vencimento.isoformat()
        }
        
        supabase.table("assinaturas").upsert(dados, on_conflict="chat_id").execute()
        logger.info(f"Degustação ativada com sucesso para o chat_id: {chat_id}")
        return True
    except Exception as e:
        logger.error(f"Erro ao iniciar degustação para o chat_id {chat_id}: {e}")
        return False

    
# --- FUNÇÕES DE OPERAÇÃO DE REGULAÇÕES E CADASTRO ---

def buscar_todas_regulacoes_ativas():
    """Busca todas as regulações cadastradas ativas no Supabase para varredura."""
    try:
        res = supabase.table("AlertaSUS_2.0").select("*").execute()
        return res.data if res and res.data else []
    except Exception as e:
        logger.error(f"Erro ao buscar regulações ativas: {e}")
        return []


def buscar_regulacoes_por_chat_id(chat_id):
    """Busca as regulações de um usuário específico, testando tipos diferentes."""
    try:
        res = supabase.table("AlertaSUS_2.0").select("*").eq("chat_id", str(chat_id)).execute()
        if res.data: 
            return res.data
        
        res = supabase.table("AlertaSUS_2.0").select("*").eq("chat_id", int(chat_id)).execute()
        return res.data if res.data else []
    except Exception as e:
        logger.error(f"Erro ao buscar regulações para o chat_id {chat_id}: {e}")
        return []


def obter_regulacao_por_numero(num_reg: str):
    """Busca uma regulação específica pelo número de regulação ou protocolo."""
    try:
        res = supabase.table("AlertaSUS_2.0").select("*").eq("numero_reg", str(num_reg)).execute()
        if res.data:
            return res.data[0]
        
        res_alt = supabase.table("AlertaSUS_2.0").select("*").eq("protocolo", str(num_reg)).execute()
        return res_alt.data[0] if res_alt and res_alt.data else None
    except Exception as e:
        logger.error(f"Erro ao obter regulação por número ({num_reg}): {e}")
        return None


def salvar_regulacao(dados_regulacao: dict):
    """Salva uma nova regulação na tabela do Supabase."""
    try:
        res = supabase.table("AlertaSUS_2.0").insert(dados_regulacao).execute()
        return res.data if res and res.data else True
    except Exception as e:
        logger.error(f"Erro ao salvar nova regulação: {e}")
        return None


def registrar_consentimento_lgpd(dados_consentimento: dict):
    """Registra o termo de consentimento LGPD do usuário."""
    try:
        res = supabase.table("lgpd_consentimentos").insert(dados_consentimento).execute()
        return res.data if res and res.data else True
    except Exception as e:
        logger.error(f"Erro ao registrar consentimento LGPD: {e}")
        return True


def atualizar_campo_regulacao(num_reg: str, campo: str, valor: str):
    """Atualiza um determinado campo de uma regulação específica."""
    try:
        res = supabase.table("AlertaSUS_2.0").update({campo: valor}).eq("numero_reg", str(num_reg)).execute()
        return res.data
    except Exception as e:
        logger.error(f"Erro ao atualizar o campo {campo} da regulação {num_reg}: {e}")
        return None


def excluir_regulacao_db(num_reg: str):
    """Exclui uma regulação do banco de dados pelo seu número/protocolo."""
    try:
        res = supabase.table("AlertaSUS_2.0").delete().eq("numero_reg", str(num_reg)).execute()
        return res.data if res and res.data else True
    except Exception as e:
        logger.error(f"Erro ao excluir regulação {num_reg}: {e}")
        return None


def desativar_regulacoes_por_chat_id(chat_id: int):
    """Desativa ou remove monitoramentos associados a um chat ID que bloqueou o bot."""
    try:
        res = supabase.table("AlertaSUS_2.0").update({"ativa": False}).eq("telegram_id", str(chat_id)).execute()
        return res.data
    except Exception as e:
        logger.error(f"Erro ao desativar regulações do chat_id {chat_id}: {e}")
        return None