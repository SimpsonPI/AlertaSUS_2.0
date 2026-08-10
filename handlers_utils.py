import re
import asyncio
import logging
from html import escape
from telegram import ReplyKeyboardMarkup, KeyboardButton
from config import supabase

# ==============================================================================
# CONSTANTES DE TEXTO E AVISOS
# ==============================================================================
AVISO_PRIVADO_HTML = (
    "<blockquote>🔒 <b>AVISO IMPORTANTE</b>\n"
    "Esta é uma <b>ferramenta privada e particular</b> desenvolvida para auxílio no acompanhamento de regulações.\n"
    "<b>Não possuímos nenhum vínculo, relação ou ligação oficial com a Fundação Municipal de Saúde (FMS)</b> ou órgãos governamentais.</blockquote>"
)

# ==============================================================================
# ESTADOS DOS FLUXOS INTERATIVOS
# ==============================================================================
(
    CONSULTAR_ID,
    # Central de Correção
    SELECIONAR_REGULACAO,
    SELECIONAR_CAMPO,
    AGUARDAR_NOVO_VALOR,
    # Exclusão
    SELECIONAR_REGULACAO_EXCLUIR,
    CONFIRMAR_EXCLUSAO,
    # Cadastro Manual
    ETAPA_SUS,
    ETAPA_NOME,
    ETAPA_CELULAR,
    ETAPA_NASCIMENTO,
    ETAPA_REGULACAO,
    ETAPA_CBO,
    ETAPA_PROCEDIMENTO,
    ETAPA_LGPD,
) = range(14)

# ==============================================================================
# TECLADOS DO BOT
# ==============================================================================
TECLADO_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📋 Verificar Todas"), KeyboardButton("🔍 Verificar Específico")],
        [KeyboardButton("➕ Cadastrar Nova"), KeyboardButton("✏️ Corrigir ID")],
        [KeyboardButton("❌ Excluir Regulação"), KeyboardButton("ℹ️ Ajuda")]
    ],
    resize_keyboard=True
)

TECLADO_CANCELAR = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🚫 Cancelar Operação")]
    ],
    resize_keyboard=True,
    one_time_keyboard=True
)

TECLADO_CONFIRMACAO = ReplyKeyboardMarkup(
    [
        [KeyboardButton("✅ Sim, confirmar exclusão")],
        [KeyboardButton("❌ Não, cancelar")]
    ],
    resize_keyboard=True,
    one_time_keyboard=True
)

# ==============================================================================
# FUNÇÕES DE FORMATAÇÃO, MÁSCARAS E LGPD
# ==============================================================================
def limpar_telefone(texto: str) -> str:
    """Remove tudo que não for dígito e garante apenas os números do telefone."""
    return re.sub(r"\D", "", texto or "")

def formatar_data_nascimento(texto: str) -> str | None:
    """Formata e valida a data no padrão DD/MM/AAAA."""
    numeros = re.sub(r"\D", "", texto or "")
    if len(numeros) == 8:
        dia, mes, ano = numeros[:2], numeros[2:4], numeros[4:]
        if 1 <= int(dia) <= 31 and 1 <= int(mes) <= 12 and 1900 <= int(ano) <= 2100:
            return f"{dia}/{mes}/{ano}"
    return None

def para_maiusculo(texto: str) -> str:
    """Converte o texto digitado para MAIÚSCULAS e remove espaços extras."""
    return (texto or "").strip().upper()

def mascarar_sus(numero_sus: str) -> str:
    """Mascara o número do Cartão SUS mantendo os 3 primeiros e os 2 últimos dígitos."""
    if not numero_sus:
        return "***"
    num_str = str(numero_sus).strip()
    if len(num_str) < 5:
        return "***"
    return f"{num_str[:3]}{'*' * (len(num_str) - 5)}{num_str[-2:]}"

def mascarar_nome(nome: str) -> str:
    """Anonimiza o nome do paciente preservando apenas as iniciais após o primeiro nome."""
    if not nome:
        return "***"
    partes = str(nome).strip().split()
    if not partes:
        return "***"
    if len(partes) == 1:
        return partes[0]
    iniciais = [partes[0]] + [f"{p[0]}." for p in partes[1:] if p]
    return " ".join(iniciais)

def _formatar_status_detalhado(status_raw: str) -> str:
    """Formata o texto de status do agendamento vindo do scraper ou BD para HTML."""
    if not status_raw:
        return "Em processamento"

    texto = str(status_raw).strip()
    texto = re.sub(r"^(status:\s*)+", "", texto, flags=re.IGNORECASE).strip()

    if "|" in texto:
        partes = [p.strip() for p in texto.split("|") if p.strip()]
        linhas_formatadas = []
        alerta_texto = ""

        for item in partes:
            item_limpo = re.sub(r"^(status:\s*)+", "", item, flags=re.IGNORECASE).strip()

            if ":" in item_limpo:
                chave, valor = item_limpo.split(":", 1)
                chave, valor = chave.strip(), valor.strip()
                chave_lower = chave.lower()

                if "id de regulação" in chave_lower or "id de regulacao" in chave_lower:
                    continue
                elif "situação" in chave_lower or "situacao" in chave_lower:
                    linhas_formatadas.append(f"📌 <b>Situação:</b> {escape(valor)}")
                elif "data" in chave_lower or "consulta marcada" in chave_lower:
                    linhas_formatadas.append(f"📅 <b>Data/Hora:</b> {escape(valor)}")
                elif "autorização" in chave_lower or "autorizacao" in chave_lower:
                    linhas_formatadas.append(f"🔑 <b>Autorização:</b> <code>{escape(valor)}</code>")
                elif "estabelecimento" in chave_lower or "executante" in chave_lower:
                    linhas_formatadas.append(f"🏥 <b>Local:</b> {escape(valor)}")
                elif "endereço" in chave_lower or "endereco" in chave_lower:
                    linhas_formatadas.append(f"📍 <b>Endereço:</b> {escape(valor)}")
                elif "telefone" in chave_lower or "contato" in chave_lower:
                    linhas_formatadas.append(f"📞 <b>Telefone:</b> {escape(valor)}")
                elif "alerta" in chave_lower or "observação" in chave_lower or "observacao" in chave_lower:
                    alerta_texto = valor
                else:
                    linhas_formatadas.append(f"• <b>{escape(chave)}:</b> {escape(valor)}")
            else:
                linhas_formatadas.append(escape(item_limpo))

        resultado = "\n".join(linhas_formatadas)
        if alerta_texto:
            resultado += f"\n\n🚨 <b>ORIENTAÇÃO IMPORTANTE:</b>\n<i>{escape(alerta_texto)}</i>"
        return resultado

    return escape(texto)

def _montar_msg_html(numero_reg: str, resultado: dict, reg_db: dict = None) -> str:
    """Monta a mensagem de resposta formatada em HTML para o usuário."""
    dados = resultado.get("dados", {}) if isinstance(resultado, dict) else {}
    reg_db = reg_db or {}

    paciente_bruto = reg_db.get("nome_paciente") or dados.get("paciente")
    if not paciente_bruto or str(paciente_bruto).strip().lower() in ["none", "null", ""]:
        paciente_exibicao = "Não informado"
    else:
        paciente_exibicao = mascarar_nome(str(paciente_bruto))

    sus_bruto = reg_db.get("numero_sus")
    sus_exibicao = mascarar_sus(sus_bruto) if sus_bruto else "Não informado"

    cbo = reg_db.get("cbo") or "Não informado"
    procedimento = reg_db.get("procedimento") or dados.get("procedimento") or "Não informado"

    status_bruto = (
        resultado.get("status_resumido")
        or resultado.get("status")
        or "Em processamento"
    ) if isinstance(resultado, dict) else "Em processamento"

    status_exibicao = _formatar_status_detalhado(status_bruto)

    return (
        f"📋 <b>Regulação:</b> <code>{escape(str(numero_reg))}</code>\n"
        f"💳 <b>Cartão SUS:</b> <code>{escape(sus_exibicao)}</code>\n"
        f"👤 <b>Paciente:</b> {escape(paciente_exibicao)}\n"
        f"🩺 <b>CBO:</b> {escape(str(cbo))}\n"
        f"📑 <b>Procedimento:</b> {escape(str(procedimento))}\n\n"
        f"📊 <b>STATUS DO AGENDAMENTO:</b>\n"
        f"{status_exibicao}"
    )

# ==============================================================================
# CONSULTAS AO SUPABASE (SÍNCRONAS EXECUTADAS EM THREADS)
# ==============================================================================
async def _buscar_paciente_por_sus(numero_sus: str) -> dict:
    """Busca o primeiro paciente associado ao número do SUS no banco."""
    try:
        def query():
            return supabase.table("AlertaSUS_2.0").select("*").eq("numero_sus", str(numero_sus)).execute()
        
        resp = await asyncio.to_thread(query)
        if resp and getattr(resp, "data", None) and len(resp.data) > 0:
            return resp.data[0]
    except Exception as e:
        logging.error(f"Erro ao buscar paciente por Cartão SUS ({numero_sus}): {e}")
    return {}

async def _buscar_regulacao_por_id_reg(numero_reg: str) -> dict:
    """Busca o registro correspondente ao número de regulação."""
    try:
        def query():
            return supabase.table("AlertaSUS_2.0").select("*").eq("numero_reg", str(numero_reg)).execute()

        resp = await asyncio.to_thread(query)
        if resp and getattr(resp, "data", None) and len(resp.data) > 0:
            return resp.data[0]
    except Exception as e:
        logging.error(f"Erro ao buscar regulação por ID ({numero_reg}): {e}")
    return {}

async def _buscar_regulacoes_db(chat_id: int) -> list:
    """Busca regulações com logs de diagnóstico no console."""
    str_chat_id = str(chat_id).strip()
    int_chat_id = int(chat_id)

    print("\n" + "="*50)
    print(f"🔍 [DIAGNÓSTICO] Chat ID recebido do Telegram: {chat_id} (Tipo: {type(chat_id)})")

    try:
        def query_debug():
            # 1. Pega 1 registro qualquer da tabela para vermos as colunas reais
            amostra = supabase.table("AlertaSUS_2.0").select("*").limit(1).execute()
            if amostra.data:
                print(f"📋 [DIAGNÓSTICO] Nomes das Colunas no Supabase: {list(amostra.data[0].keys())}")
            else:
                print("⚠️ [DIAGNÓSTICO] A tabela 'AlertaSUS_2.0' parece estar totalmente vazia!")

            # 2. Tenta buscar pelo chat_id
            res = supabase.table("AlertaSUS_2.0").select("*").or_(f"telegram_chat_id.eq.{int_chat_id},telegram_chat_id.eq.{str_chat_id}").execute()
            return res

        resp = await asyncio.to_thread(query_debug)
        print(f"📊 [DIAGNÓSTICO] Registros encontrados: {len(resp.data if resp.data else [])}")
        print("="*50 + "\n", flush=True)

        if resp and getattr(resp, "data", None):
            return resp.data

    except Exception as e:
        print(f"❌ [DIAGNÓSTICO] Erro na Query: {e}", flush=True)
        logging.error(f"Erro ao consultar Supabase para chat_id {chat_id}: {e}")

    return []