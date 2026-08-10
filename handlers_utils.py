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
    ETAPA_LGPD
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
    return re.sub(r"\D", "", texto)

def formatar_data_nascimento(texto: str) -> str | None:
    """Formata/valida automaticamente para DD/MM/AAAA."""
    numeros = re.sub(r"\D", "", texto)
    if len(numeros) == 8:
        dia, mes, ano = numeros[:2], numeros[2:4], numeros[4:]
        if 1 <= int(dia) <= 31 and 1 <= int(mes) <= 12 and 1900 <= int(ano) <= 2100:
            return f"{dia}/{mes}/{ano}"
    return None

def para_maiusculo(texto: str) -> str:
    """Converte o texto digitado para MAIÚSCULAS e remove espaços extras."""
    return texto.strip().upper()

def mascarar_sus(numero_sus: str) -> str:
    """Mascara o número do Cartão SUS para logs/exibição."""
    if not numero_sus or len(str(numero_sus)) < 5:
        return "***"
    num_str = str(numero_sus).strip()
    return f"{num_str[:3]}{'*' * (len(num_str) - 5)}{num_str[-2:]}"

def mascarar_nome(nome: str) -> str:
    """Anonimiza o nome do paciente preservando apenas iniciais."""
    if not nome:
        return "***"
    partes = str(nome).strip().split()
    if len(partes) <= 1:
        return partes[0]
    iniciais = [partes[0]] + [f"{p[0]}." for p in partes[1:]]
    return " ".join(iniciais)

def _formatar_status_detalhado(status_raw: str) -> str:
    """Formata o texto retornado pelo scraper ou banco de dados."""
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
                elif "alerta" in chave_lower or "observação" in chave_lower:
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
    """Monta a mensagem em HTML formatada."""
    dados = resultado.get("dados", {})
    
    paciente_bruto = (reg_db.get("nome_paciente") if reg_db else None) or dados.get("paciente")
    if not paciente_bruto or str(paciente_bruto).strip().lower() in ["none", "null", ""]:
        paciente_exibicao = "Não informado"
    else:
        paciente_exibicao = mascarar_nome(str(paciente_bruto))

    sus_bruto = reg_db.get("numero_sus") if reg_db else None
    sus_exibicao = mascarar_sus(sus_bruto) if sus_bruto else "Não informado"
        
    cbo = (reg_db.get("cbo") if reg_db else None) or "Não informado"
    procedimento = (reg_db.get("procedimento") if reg_db else None) or dados.get("procedimento") or "Não informado"
    
    status_bruto = resultado.get("status_resumido") or resultado.get("status") or "Em processamento"
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

async def _buscar_paciente_por_sus(numero_sus: str) -> dict:
    try:
        resp = await asyncio.to_thread(
            lambda: supabase.table("AlertaSUS_2.0").select("*").eq("numero_sus", str(numero_sus)).execute()
        )
        if resp and getattr(resp, "data", None) and len(resp.data) > 0:
            return resp.data[0]
    except Exception as e:
        logging.error(f"Erro ao buscar paciente por Cartão SUS ({numero_sus}): {e}")
    return {}

async def _buscar_regulacao_por_id_reg(numero_reg: str) -> dict:
    try:
        resp = await asyncio.to_thread(
            lambda: supabase.table("AlertaSUS_2.0").select("*").eq("numero_reg", str(numero_reg)).execute()
        )
        if resp and getattr(resp, "data", None) and len(resp.data) > 0:
            return resp.data[0]
    except Exception as e:
        logging.error(f"Erro ao buscar regulação por ID ({numero_reg}): {e}")
    return {}

async def _buscar_regulacoes_db(chat_id: int) -> list:
    str_chat_id = str(chat_id).strip()
    try:
        resp = await asyncio.to_thread(
            lambda: supabase.table("AlertaSUS_2.0").select("*").execute()
        )
        if resp and getattr(resp, "data", None):
            regulacoes_usuario = []
            for row in resp.data:
                valores_linha = [str(val).strip() for val in row.values()]
                if str_chat_id in valores_linha:
                    regulacoes_usuario.append(row)
            return regulacoes_usuario
    except Exception as e:
        logging.error(f"Erro ao consultar Supabase: {e}")
    return []