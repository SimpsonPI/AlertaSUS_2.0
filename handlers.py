import re
import asyncio
import logging
import traceback
from html import escape
from datetime import datetime

# Importação do Módulo Antispam / Rate Limiting
from rate_limiter import rate_limit

# 1. Componentes visuais do Telegram
from telegram import (
    Update,
    BotCommand,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

# 2. Importações do Banco de Dados
from database import (
    buscar_regulacoes_por_chat_id,
    deletar_regulacao_por_id,
)

# 2. Manipuladores de eventos e fluxos de conversa
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters
)

# 3. Configurações e Scraper do projeto
from config import supabase
from scraper import consultar_status_fms, formatar_data_br, nome_paciente_exibicao

# ==============================================================================
# CONSTANTES DE TEXTO E AVISOS
# ==============================================================================
AVISO_PRIVADO_HTML = (
    "<blockquote>🔒 <b>AVISO IMPORTANTE</b>\n"
    "Esta é uma <b>ferramenta privada e particular</b> desenvolvida para auxílio no acompanhamento de regulações.\n"
    "<b>Não possuímos nenhum vínculo, relação ou ligação oficial com a Fundação Municipal de Saúde (FMS)</b> ou órgãos governamentais.</blockquote>"
)

# ==========================================
# FUNÇÕES DE FORMATACAO, MÁSCARAS E LGPD
# ==========================================
def limpar_telefone(texto: str) -> str:
    """Remove tudo que não for dígito e garante apenas os números do telefone."""
    return re.sub(r"\D", "", texto)

def formatar_data_nascimento(texto: str) -> str | None:
    """
    Recebe apenas números (ex: 15081990) ou com barra (15/08/1990)
    e formata/valida automaticamente para DD/MM/AAAA.
    """
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
    """Mascara o número do Cartão SUS para logs de terminal (Ex: 898************89)"""
    if not numero_sus or len(str(numero_sus)) < 5:
        return "***"
    num_str = str(numero_sus).strip()
    return f"{num_str[:3]}{'*' * (len(num_str) - 5)}{num_str[-2:]}"

def mascarar_nome(nome: str) -> str:
    """Anonimiza o nome do paciente preservando apenas iniciais (Ex: MARIA A. P. O.)"""
    if not nome:
        return "***"
    partes = str(nome).strip().split()
    if len(partes) <= 1:
        return partes[0]
    iniciais = [partes[0]] + [f"{p[0]}." for p in partes[1:]]
    return " ".join(iniciais)


# ==========================================
# 1. ESTADOS DOS FLUXOS INTERATIVOS
# ==========================================
(
    CONSULTAR_ID,
    # --- ESTADOS DA CENTRAL DE CORREÇÃO INTERATIVA ---
    SELECIONAR_REGULACAO,
    SELECIONAR_CAMPO,
    AGUARDAR_NOVO_VALOR,
    # --- ESTADOS DE EXCLUSÃO INTERATIVA ---
    SELECIONAR_REGULACAO_EXCLUIR,
    CONFIRMAR_EXCLUSAO,
    # --- ESTADOS DO FORMULÁRIO INTERATIVO NO BOT ---
    ETAPA_SUS,
    ETAPA_NOME,
    ETAPA_CELULAR,
    ETAPA_NASCIMENTO,
    ETAPA_REGULACAO,
    ETAPA_CBO,
    ETAPA_PROCEDIMENTO,
    ETAPA_LGPD
) = range(14)

# ==========================================
# 2. TECLADOS DO BOT
# ==========================================
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

# ==========================================
# 3. FUNÇÕES AUXILIARES E INTERCEPTADORES
# ==========================================

async def verificar_se_e_menu_e_executar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Intercepta cliques do menu ou cancelamentos durante conversas ativas."""
    if not update.message or not update.message.text:
        return False

    texto = update.message.text.strip()

    if "Cancelar" in texto or texto == "/cancelar":
        await cancelar_operacao(update, context)
        return True
    elif "Cadastrar Nova" in texto:
        await iniciar_cadastro_manual(update, context)
        return True
    elif "Verificar Todas" in texto:
        await comando_verificar_todas(update, context)
        return True
    elif "Verificar Específico" in texto:
        await iniciar_verificar_especifico(update, context)
        return True
    elif "Corrigir ID" in texto:
        await iniciar_corrigir(update, context)
        return True
    elif "Excluir Regulação" in texto:
        await iniciar_excluir(update, context)
        return True
    elif "Ajuda" in texto:
        await comando_ajuda(update, context)
        return True
    elif texto.startswith("/"):
        if texto.startswith("/start"):
            await start(update, context)
        elif texto.startswith("/ajuda"):
            await comando_ajuda(update, context)
        elif texto.startswith("/cadastrar"):
            await iniciar_cadastro_manual(update, context)
        elif texto.startswith("/verificar"):
            await comando_verificar_todas(update, context)
        elif texto.startswith("/consultar"):
            await iniciar_verificar_especifico(update, context)
        elif texto.startswith("/corrigir"):
            await iniciar_corrigir(update, context)
        elif texto.startswith("/excluir"):
            await iniciar_excluir(update, context)
        return True

    return False

def _montar_msg_html(numero_reg: str, resultado: dict, reg_db: dict = None) -> str:
    """Monta a mensagem em HTML formatada com Regulação, Cartão SUS (mascarado), Paciente (mascarado), CBO, Procedimento e Status."""
    dados = resultado.get("dados", {})
    
    # 1. Nome do paciente com mascaramento LGPD
    paciente_bruto = (reg_db.get("nome_paciente") if reg_db else None) or dados.get("paciente")
    if not paciente_bruto or str(paciente_bruto).strip().lower() in ["none", "null", ""]:
        paciente_exibicao = "Não informado"
    else:
        paciente_exibicao = mascarar_nome(str(paciente_bruto))

    # 2. Cartão SUS com mascaramento LGPD
    sus_bruto = reg_db.get("numero_sus") if reg_db else None
    sus_exibicao = mascarar_sus(sus_bruto) if sus_bruto else "Não informado"
        
    cbo = (reg_db.get("cbo") if reg_db else None) or "Não informado"
    procedimento = (reg_db.get("procedimento") if reg_db else None) or dados.get("procedimento") or "Não informado"
    status = resultado.get("status_resumido", "Em processamento")

    return (
        f"📋 <b>Regulação:</b> <code>{escape(str(numero_reg))}</code>\n"
        f"💳 <b>Cartão SUS:</b> <code>{escape(sus_exibicao)}</code>\n"
        f"👤 <b>Paciente:</b> {escape(paciente_exibicao)}\n"
        f"🩺 <b>CBO:</b> {escape(str(cbo))}\n"
        f"📑 <b>Procedimento:</b> {escape(str(procedimento))}\n"
        f"📊 <b>Status:</b> {escape(str(status))}"
    )

async def _buscar_paciente_por_sus(numero_sus: str) -> dict:
    """Busca dados de um paciente no Supabase pelo número do Cartão SUS."""
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
    """Busca uma regulação específica no Supabase pelo número da regulação."""
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
    """Busca todas as regulações do usuário no Supabase."""
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

# ==========================================
# 4. COMANDOS BÁSICOS E NAVEGAÇÃO
# ==========================================

# 1. Definição da constante
AVISO_PRIVADO_HTML = (
    "<blockquote>🔒 <b>AVISO IMPORTANTE</b>\n"
    "Esta é uma <b>ferramenta privada e particular</b> desenvolvida para auxílio no acompanhamento de regulações.\n"
    "<b>Não possuímos nenhum vínculo, relação ou ligação oficial com a Fundação Municipal de Saúde (FMS)</b> ou órgãos governamentais.</blockquote>"
)

# 2. Comando /start
@rate_limit(max_mensagens=5, janela_segundos=60)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    chat_id = update.effective_chat.id
    mensagem = (
        f"👋 Bem-vindo ao <b>AlertaSUS 2.0</b>!\n\n"
        f"🔑 <b>Seu ID do Chat:</b> <code>{chat_id}</code>\n\n"
        f"{AVISO_PRIVADO_HTML}\n\n"
        "Escolha uma opção no menu abaixo para começar:"
    )
    await update.message.reply_text(mensagem, reply_markup=TECLADO_MENU, parse_mode="HTML")
    return ConversationHandler.END


# 3. Comando /ajuda
@rate_limit(max_mensagens=5, janela_segundos=60)
async def comando_ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    chat_id = update.effective_chat.id
    texto_ajuda = (
        "ℹ️ <b>Central de Ajuda - AlertaSUS 2.0</b>\n\n"
        f"🔑 <b>Seu ID do Chat:</b> <code>{chat_id}</code>\n\n"
        f"{AVISO_PRIVADO_HTML}\n\n"
        "• <b>➕ Cadastrar Nova:</b> Cadastre seus dados e ID de Regulação passo a passo.\n"
        "• <b>📋 Verificar Todas:</b> Consulta o status de todos os seus IDs cadastrados.\n"
        "• <b>🔍 Verificar Específico:</b> Consulta um único ID informado na hora.\n"
        "• <b>✏️ Corrigir ID:</b> Altera ID, Cartão SUS ou Nome de uma regulação de forma interativa.\n"
        "• <b>❌ Excluir Regulação:</b> Remove um ID mediante confirmação.\n\n"
        "⏰ <b>Varreduras automáticas:</b> Diariamente às 08:00 e 18:00."
    )
    await update.message.reply_text(texto_ajuda, reply_markup=TECLADO_MENU, parse_mode="HTML")
    return ConversationHandler.END

async def cancelar_operacao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ Operação cancelada.", reply_markup=TECLADO_MENU)
    return ConversationHandler.END

# ==========================================
# 5. CADASTRO INTERATIVO NO BOT
# ==========================================

@rate_limit(max_mensagens=5, janela_segundos=60)
async def iniciar_cadastro_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    msg = (
        "📝 <b>Cadastro de Alerta SUS</b>\n\n"
        "1️⃣ Digite o seu <b>Número do Cartão SUS</b>:\n"
        "<i>(Apenas os 15 números do cartão)</i>"
    )
    await update.message.reply_text(msg, reply_markup=TECLADO_CANCELAR, parse_mode="HTML")
    return ETAPA_SUS

async def receber_sus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    numero_sus = re.sub(r"\D", "", update.message.text.strip())

    if not numero_sus:
        await update.message.reply_text("⚠️ Por favor, digite apenas números para o Cartão SUS:")
        return ETAPA_SUS

    context.user_data['numero_sus'] = numero_sus
    
    msg_aguarde = await update.message.reply_text("🔍 <i>Verificando dados do Cartão SUS no sistema...</i>", parse_mode="HTML")
    paciente_existente = await _buscar_paciente_por_sus(numero_sus)
    await msg_aguarde.delete()

    if paciente_existente and paciente_existente.get("nome_paciente"):
        context.user_data['nome_paciente'] = paciente_existente.get("nome_paciente")
        context.user_data['celular'] = paciente_existente.get("celular")
        context.user_data['data_nascimento'] = paciente_existente.get("data_nascimento")

        await update.message.reply_text(
            f"✅ <b>Paciente Encontrado!</b>\n\n"
            f"👤 <b>Nome:</b> {escape(str(context.user_data['nome_paciente']))}\n"
            f"📱 <b>Celular:</b> {escape(str(context.user_data['celular'] or 'N/I'))}\n"
            f"📅 <b>Nascimento:</b> {escape(str(context.user_data['data_nascimento'] or 'N/I'))}\n\n"
            f"2️⃣ Digite o <b>Número de Regulação (ID)</b> para esta consulta:",
            parse_mode="HTML",
            reply_markup=TECLADO_CANCELAR
        )
        return ETAPA_REGULACAO
    else:
        await update.message.reply_text(
            "ℹ️ Cartão SUS não localizado em cadastros anteriores.\n\n"
            "2️⃣ Por favor, digite o <b>Nome Completo do Paciente</b>:",
            parse_mode="HTML",
            reply_markup=TECLADO_CANCELAR
        )
        return ETAPA_NOME

async def receber_nome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    # Converte o nome digitado automaticamente para MAIÚSCULAS
    nome_formatado = para_maiusculo(update.message.text)
    context.user_data["nome_paciente"] = nome_formatado

    await update.message.reply_text(
        "3️⃣ Qual o <b>Celular / WhatsApp</b> com DDD?\n<i>Digite apenas os números (ex: 86999999999)</i>",
        reply_markup=TECLADO_CANCELAR,
        parse_mode="HTML"
    )
    return ETAPA_CELULAR

async def receber_celular(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    # Garante apenas números
    celular_limpo = limpar_telefone(update.message.text)

    # Valida telefone com DDD (10 ou 11 dígitos)
    if len(celular_limpo) not in (10, 11):
        await update.message.reply_text(
            "⚠️ <b>Telefone inválido!</b>\nDigite apenas os números com DDD (ex: <code>86999999999</code>):",
            reply_markup=TECLADO_CANCELAR,
            parse_mode="HTML"
        )
        return ETAPA_CELULAR

    context.user_data["celular"] = celular_limpo

    await update.message.reply_text(
        "4️⃣ Qual a <b>Data de Nascimento</b>?\n<i>Digite apenas os 8 números (ex: 15081990)</i>",
        reply_markup=TECLADO_CANCELAR,
        parse_mode="HTML"
    )
    return ETAPA_NASCIMENTO

async def receber_nascimento(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    texto_data = update.message.text
    data_formatada = formatar_data_nascimento(texto_data)

    if not data_formatada:
        await update.message.reply_text(
            "⚠️ <b>Data de Nascimento inválida!</b>\nDigite apenas os 8 números no formato DDMMAAAA (ex: <code>15081990</code>):",
            reply_markup=TECLADO_CANCELAR,
            parse_mode="HTML"
        )
        return ETAPA_NASCIMENTO

    context.user_data["data_nascimento"] = data_formatada

    await update.message.reply_text(
        "5️⃣ Digite o <b>Número de Regulação (ID)</b>:\n<i>(Apenas números, ex: 12345678)</i>",
        reply_markup=TECLADO_CANCELAR,
        parse_mode="HTML"
    )
    return ETAPA_REGULACAO

async def receber_regulacao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    regulacao = re.sub(r"\D", "", update.message.text.strip())
    
    if not regulacao:
        await update.message.reply_text("⚠️ Por favor, digite apenas números para o ID de Regulação:")
        return ETAPA_REGULACAO

    context.user_data['numero_reg'] = regulacao
    
    msg_aguarde = await update.message.reply_text("🔍 <i>Buscando informações da regulação no SUS...</i>", parse_mode="HTML")
    try:
        resultado = await consultar_status_fms(regulacao)
        if resultado and resultado.get("sucesso"):
            context.user_data['status_inicial'] = resultado.get("status_resumido", "Consulta realizada")
            dados_fms = resultado.get("dados", {})
            if dados_fms.get("procedimento"):
                context.user_data['procedimento_sugerido'] = dados_fms.get("procedimento")
        else:
            context.user_data['status_inicial'] = "Cadastrado / Aguardando FMS"
    except Exception as e:
        logging.error(f"Erro ao consultar FMS no cadastro: {e}")
        context.user_data['status_inicial'] = "Cadastrado / Aguardando FMS"

    await msg_aguarde.delete()

    await update.message.reply_text(
        "📌 Digite o <b>CBO</b> (Código ou Nome da Especialidade/Ocupação):\n<i>Ex: Clínico Geral, Cardiologia, 225125...</i>",
        reply_markup=TECLADO_CANCELAR,
        parse_mode="HTML"
    )
    return ETAPA_CBO

async def receber_cbo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    # Converte CBO para MAIÚSCULAS
    context.user_data["cbo"] = para_maiusculo(update.message.text)
    
    procedimento_sugerido = context.user_data.get("procedimento_sugerido", "")
    msg_extra = f"\n<i>(Identificado na FMS: {procedimento_sugerido})</i>" if procedimento_sugerido else ""

    await update.message.reply_text(
        f"📑 Digite o Nome do <b>PROCEDIMENTO</b> ou Exame:{msg_extra}",
        reply_markup=TECLADO_CANCELAR,
        parse_mode="HTML"
    )
    return ETAPA_PROCEDIMENTO

async def receber_procedimento(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    # Converte Procedimento para MAIÚSCULAS
    context.user_data["procedimento"] = para_maiusculo(update.message.text)

    termo_lgpd = (
        "<b>🔒 Termo de Consentimento (LGPD)</b>\n\n"
        "Ao confirmar, você autoriza o AlertaSUS a utilizar seus dados para consultar "
        "sua posição na fila do SUS e enviar alertas pelo Telegram. Seus dados são protegidos e não serão compartilhados.\n\n"
        "Você concorda com estes termos?"
    )
    
    teclado_lgpd = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Sim, Concordo e Ativar", callback_data="aceitar_lgpd")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_cadastro")]
    ])
    
    await update.message.reply_text(termo_lgpd, reply_markup=teclado_lgpd, parse_mode="HTML")
    return ETAPA_LGPD

async def finalizar_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancelar_cadastro":
        await query.message.edit_text("❌ Cadastro cancelado.")
        await query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)
        context.user_data.clear()
        return ConversationHandler.END

    chat_id = update.effective_chat.id
    dados = {
        "chat_id": int(chat_id),
        "numero_sus": str(context.user_data.get("numero_sus")),
        "numero_reg": str(context.user_data.get("numero_reg")),
        "nome_paciente": str(context.user_data.get("nome_paciente")),
        "celular": context.user_data.get("celular"),
        "data_nascimento": context.user_data.get("data_nascimento"),
        "cbo": context.user_data.get("cbo"),
        "procedimento": context.user_data.get("procedimento"),
        "status_anterior": context.user_data.get("status_inicial", "Cadastrado")
    }

    try:
        await asyncio.to_thread(
            lambda: supabase.table("AlertaSUS_2.0").insert(dados).execute()
        )
        await query.message.edit_text(
            f"🎉 <b>Alertas Ativados com Sucesso!</b>\n\n"
            f"🆔 <b>Cartão SUS:</b> <code>{escape(str(dados['numero_sus']))}</code>\n"
            f"📌 <b>ID de Regulação:</b> <code>{escape(str(dados['numero_reg']))}</code>\n"
            f"👤 <b>Paciente:</b> {escape(str(dados['nome_paciente']))}\n"
            f"🩺 <b>CBO:</b> {escape(str(dados['cbo']))}\n"
            f"📑 <b>Procedimento:</b> {escape(str(dados['procedimento']))}\n\n"
            f"Avisaremos você aqui no chat assim que a sua posição mudar na fila!",
            parse_mode="HTML"
        )
        await query.message.reply_text("O que deseja fazer agora?", reply_markup=TECLADO_MENU)
    except Exception as e:
        logging.error(f"Erro ao salvar no Supabase: {e}")
        await query.message.edit_text("⚠️ Ocorreu um erro ao salvar o cadastro. Tente novamente mais tarde.")
        await query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)

    context.user_data.clear()
    return ConversationHandler.END

# ==========================================
# 6. CONSULTAS E OPERAÇÕES DE BANCO DE DADOS
# ==========================================

@rate_limit(max_mensagens=5, janela_segundos=60)
async def comando_verificar_todas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    chat_id = update.effective_chat.id
    msg_espera = await update.message.reply_text("🔍 <b>Consultando suas regulações no sistema...</b>", parse_mode="HTML")

    try:
        regulacoes = await _buscar_regulacoes_db(chat_id)
        if not regulacoes:
            await msg_espera.edit_text(
                "ℹ️ Você não possui nenhuma regulação cadastrada.\nUtilize a opção <b>➕ Cadastrar Nova</b> para cadastrar.",
                parse_mode="HTML"
            )
            return ConversationHandler.END

        await msg_espera.delete()

        for reg in regulacoes:
            numero_reg = str(reg.get("numero_reg", "")).strip()
            if not numero_reg:
                continue

            try:
                resultado = await consultar_status_fms(numero_reg)
                if resultado.get("sucesso"):
                    msg_html = _montar_msg_html(numero_reg, resultado, reg)
                    await update.message.reply_text(msg_html, parse_mode="HTML")
                else:
                    msg_erro = resultado.get("mensagem") or "Não foi possível consultar esta regulação."
                    await update.message.reply_text(
                        f"⚠️ <b>ID {escape(numero_reg)}:</b> {escape(msg_erro)}",
                        parse_mode="HTML"
                    )
            except Exception as item_err:
                logging.error(f"Erro ao processar regulação {numero_reg}: {item_err}")

    except Exception as e:
        logging.error(f"Erro ao consultar regulações: {traceback.format_exc()}")
        await msg_espera.edit_text("❌ Ocorreu um erro ao acessar o banco de dados. Tente novamente em instantes.")

    return ConversationHandler.END

@rate_limit(max_mensagens=5, janela_segundos=60)
async def iniciar_verificar_especifico(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "🔍 Digite o <b>Número da Regulação (ID)</b> que deseja consultar agora:",
        reply_markup=TECLADO_CANCELAR,
        parse_mode="HTML"
    )
    return CONSULTAR_ID

async def processar_verificar_especifico(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    texto = update.message.text
    numero_reg = re.sub(r"\D", "", texto)

    if not numero_reg:
        await update.message.reply_text("⚠️ Por favor, digite apenas os números do ID da regulação:", reply_markup=TECLADO_CANCELAR)
        return CONSULTAR_ID

    msg_espera = await update.message.reply_text(f"🔎 Pesquisando ID <code>{escape(numero_reg)}</code>...", parse_mode="HTML")

    reg_db = await _buscar_regulacao_por_id_reg(numero_reg)
    resultado = await consultar_status_fms(numero_reg)

    await msg_espera.delete()

    if resultado.get("sucesso"):
        msg_html = _montar_msg_html(numero_reg, resultado, reg_db)
        await update.message.reply_text(msg_html, parse_mode="HTML", reply_markup=TECLADO_MENU)
    else:
        msg_erro = resultado.get("mensagem") or "Regulação não encontrada na FMS."
        await update.message.reply_text(f"❌ {escape(msg_erro)}", parse_mode="HTML", reply_markup=TECLADO_MENU)

    context.user_data.clear()
    return ConversationHandler.END

# ==========================================
# 7. CENTRAL DE CORREÇÃO INTERATIVA (BOTÕES INLINE)
# ==========================================

@rate_limit(max_mensagens=5, janela_segundos=60)
async def iniciar_corrigir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Passo 1: Lista as regulações do usuário em botões interativos."""
    context.user_data.clear()
    chat_id = update.effective_chat.id
    regulacoes = await _buscar_regulacoes_db(chat_id)

    if not regulacoes:
        await update.message.reply_text(
            "⚠️ Você não possui nenhuma regulação cadastrada para corrigir.",
            reply_markup=TECLADO_MENU
        )
        return ConversationHandler.END

    teclado = []
    for reg in regulacoes:
        num_reg = str(reg.get("numero_reg", "")).strip()
        nome = mascarar_nome(str(reg.get("nome_paciente", "Não informado")))
        
        teclado.append([
            InlineKeyboardButton(
                f"📋 Regulação {num_reg} - {nome}", 
                callback_data=f"corr_reg_{num_reg}"
            )
        ])

    teclado.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_corrigir")])

    await update.message.reply_text(
        "✏️ <b>Central de Correção de Dados</b>\n\n"
        "Selecione abaixo qual regulação você deseja alterar:",
        reply_markup=InlineKeyboardMarkup(teclado),
        parse_mode="HTML"
    )
    return SELECIONAR_REGULACAO


async def selecionar_regulacao_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Passo 2: Captura a regulação selecionada e exibe os campos alteráveis."""
    query = update.callback_query
    await query.answer()

    if query.data == "cancelar_corrigir":
        await query.edit_message_text("❌ Operação de correção cancelada.")
        await query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)
        context.user_data.clear()
        return ConversationHandler.END

    numero_reg = query.data.replace("corr_reg_", "")
    context.user_data["reg_corrigir"] = numero_reg

    teclado = [
        [InlineKeyboardButton("🆔 Número da Regulação", callback_data="corr_campo_numero_reg")],
        [InlineKeyboardButton("👤 Nome do Paciente", callback_data="corr_campo_nome_paciente")],
        [InlineKeyboardButton("💳 Cartão SUS", callback_data="corr_campo_numero_sus")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_corrigir")]
    ]

    await query.edit_message_text(
        f"📋 Regulação selecionada: <code>{escape(numero_reg)}</code>\n\n"
        f"<b>Qual informação você deseja alterar?</b>",
        reply_markup=InlineKeyboardMarkup(teclado),
        parse_mode="HTML"
    )
    return SELECIONAR_CAMPO


async def selecionar_campo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Passo 3: Registra o campo escolhido e solicita o novo valor ao usuário."""
    query = update.callback_query
    await query.answer()

    if query.data == "cancelar_corrigir":
        await query.edit_message_text("❌ Operação de correção cancelada.")
        await query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)
        context.user_data.clear()
        return ConversationHandler.END

    campo = query.data.replace("corr_campo_", "")
    context.user_data["campo_corrigir"] = campo

    mural_campos = {
        "numero_reg": ("Número da Regulação", "digite o novo número da regulação (apenas números)"),
        "nome_paciente": ("Nome do Paciente", "digite o nome completo do paciente"),
        "numero_sus": ("Cartão SUS", "digite o novo número do Cartão SUS (15 dígitos)")
    }

    nome_amigavel, instrucao = mural_campos.get(campo, ("Campo", "digite o novo valor"))

    await query.edit_message_text(
        f"✏️ <b>Alterando: {nome_amigavel}</b>\n\n"
        f"Por favor, {instrucao}:",
        parse_mode="HTML"
    )
    return AGUARDAR_NOVO_VALOR


async def salvar_novo_valor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Passo 4: Valida a entrada, grava no Supabase e confirma a alteração."""
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    novo_valor = update.message.text.strip()

    campo = context.user_data.get("campo_corrigir")
    numero_reg_antigo = context.user_data.get("reg_corrigir")
    chat_id = update.effective_chat.id

    if campo == "nome_paciente":
        novo_valor = para_maiusculo(novo_valor)

    if campo in ["numero_reg", "numero_sus"] and not novo_valor.isdigit():
        await update.message.reply_text("⚠️ O valor digitado deve conter apenas números. Tente novamente:")
        return AGUARDAR_NOVO_VALOR

    if campo == "numero_sus" and len(novo_valor) != 15:
        await update.message.reply_text("⚠️ O Cartão SUS deve possuir exatamente 15 dígitos. Tente novamente:")
        return AGUARDAR_NOVO_VALOR

    try:
        dados_atualizacao = {campo: novo_valor}

        # Se for atualização do número da regulação, atualiza o status FMS correspondente
        if campo == "numero_reg":
            resultado_fms = await consultar_status_fms(novo_valor)
            novo_status = resultado_fms.get("status_resumido", "Atualizado") if resultado_fms.get("sucesso") else "Atualizado"
            dados_atualizacao["status_anterior"] = novo_status

        resp = await asyncio.to_thread(
            lambda: supabase.table("AlertaSUS_2.0")
            .update(dados_atualizacao)
            .eq("chat_id", int(chat_id))
            .eq("numero_reg", str(numero_reg_antigo))
            .execute()
        )

        if campo == "nome_paciente":
            exibicao_valor = mascarar_nome(novo_valor)
        elif campo == "numero_sus":
            exibicao_valor = mascarar_sus(novo_valor)
        else:
            exibicao_valor = escape(novo_valor)

        await update.message.reply_text(
            f"✅ <b>Informação atualizada com sucesso!</b>\n\n"
            f"📋 Regulação: <code>{escape(numero_reg_antigo)}</code>\n"
            f"🔄 Novo valor: <b>{exibicao_valor}</b>",
            reply_markup=TECLADO_MENU,
            parse_mode="HTML"
        )

    except Exception as e:
        logging.error(f"Erro ao atualizar registro no Supabase: {e}")
        await update.message.reply_text("❌ Erro ao salvar a alteração no banco de dados. Tente novamente mais tarde.", reply_markup=TECLADO_MENU)

    context.user_data.clear()
    return ConversationHandler.END


async def cancelar_corrigir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancela o fluxo de correção se acionado pelo fallback."""
    context.user_data.clear()
    await update.message.reply_text("❌ Operação de correção cancelada.", reply_markup=TECLADO_MENU)
    return ConversationHandler.END

# ==========================================
# 8. EXCLUSÃO INTERATIVA DE REGULAÇÃO
# ==========================================

async def iniciar_excluir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Lista as regulações salvas para exclusão no mesmo padrão visual do Corrigir ID (LGPD)."""
    try:
        chat_id = update.effective_chat.id
        regulacoes = buscar_regulacoes_por_chat_id(chat_id)

        if not regulacoes:
            mensagem = "⚠️ **Nenhuma regulação encontrada para o seu ID de chat.**"
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.edit_message_text(mensagem, parse_mode="Markdown")
            else:
                await update.message.reply_text(mensagem, parse_mode="Markdown")
            return ConversationHandler.END

        keyboard = []
        for reg in regulacoes:
            num_reg = reg.get("numero_reg", "N/A")
            nome_completo = reg.get("nome_paciente", "").strip()

            partes = nome_completo.split()
            if partes:
                primeiro_nome = partes[0].upper()
                iniciais_sobrenomes = [f"{p[0].upper()}." for p in partes[1:] if p]
                nome_formatado = f"{primeiro_nome} {' '.join(iniciais_sobrenomes)}".strip()
            else:
                nome_formatado = "Paciente"

            texto_botao = f"🗑️ Regulação {num_reg} - {nome_formatado}"
            keyboard.append([InlineKeyboardButton(texto_botao, callback_data=f"excluir_sel_{num_reg}")])

        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_excluir")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        texto = "❌ **Exclusão de Regulação**\n\nClique na regulação que deseja excluir:"

        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(texto, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            await update.message.reply_text(texto, reply_markup=reply_markup, parse_mode="Markdown")

        return SELECIONAR_REGULACAO_EXCLUIR

    except Exception as e:
        print(f"ERRO em iniciar_excluir: {e}", flush=True)
        if update.message:
            await update.message.reply_text(f"⚠️ Ocorreu um erro ao carregar as regulações: `{e}`", parse_mode="Markdown")
        return ConversationHandler.END


async def selecionar_regulacao_excluir_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Solicita a confirmação de exclusão para a regulação selecionada."""
    query = update.callback_query
    await query.answer()

    if query.data == "cancelar_excluir":
        await query.edit_message_text("❌ **Operação cancelada.**", parse_mode="Markdown")
        return ConversationHandler.END

    num_reg = query.data.replace("excluir_sel_", "")
    context.user_data["regulacao_para_excluir"] = num_reg

    keyboard = [
        [InlineKeyboardButton("✅ Confirmar Exclusão", callback_data="confirmar_exclusao")],
        [InlineKeyboardButton("🚫 Cancelar", callback_data="cancelar_excluir")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    texto = (
        f"⚠️ **Atenção!**\n\n"
        f"Tem certeza que deseja excluir a regulação **{num_reg}**?\n"
        f"Esta ação não poderá ser desfeita."
    )

    await query.edit_message_text(texto, reply_markup=reply_markup, parse_mode="Markdown")
    return CONFIRMAR_EXCLUSAO


async def confirmar_exclusao_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Executa a exclusão no banco de dados após a confirmação."""
    query = update.callback_query
    await query.answer()

    if query.data == "cancelar_excluir":
        await query.edit_message_text("❌ **Operação cancelada.**", parse_mode="Markdown")
        return ConversationHandler.END

    chat_id = update.effective_chat.id
    num_reg = context.user_data.get("regulacao_para_excluir")

    if not num_reg:
        await query.edit_message_text("⚠️ **Erro ao identificar a regulação.** Operação cancelada.")
        return ConversationHandler.END

    sucesso = deletar_regulacao_por_id(chat_id, num_reg)

    if sucesso:
        await query.edit_message_text(f"✅ **Regulação {num_reg} excluída com sucesso!**", parse_mode="Markdown")
    else:
        await query.edit_message_text(f"❌ **Erro ao excluir a regulação {num_reg}.** Tente novamente.", parse_mode="Markdown")

    context.user_data.clear()
    return ConversationHandler.END


async def cancelar_excluir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancela o fluxo de exclusão."""
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("❌ **Operação cancelada.**", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ **Operação cancelada.**", parse_mode="Markdown")
    
    context.user_data.clear()
    return ConversationHandler.END

# ==========================================
# 9. CONFIGURAÇÕES E VARREDURA AUTOMÁTICA
# ==========================================

async def configurar_menu_comandos(application):
    comandos = [
        BotCommand("start", "Iniciar bot e exibir menu principal"),
        BotCommand("cadastrar", "Cadastrar nova regulação"),
        BotCommand("verificar", "Verificar todas as regulações"),
        BotCommand("consultar", "Verificar regulação específica"),
        BotCommand("corrigir", "Corrigir dados de regulação"),
        BotCommand("excluir", "Excluir regulação com confirmação"),
        BotCommand("ajuda", "Central de ajuda")
    ]
    await application.bot.set_my_commands(comandos)

async def executar_varredura_automatica(app):
    """Varre todas as regulações cadastradas e notifica os usuários sobre mudanças de status."""
    logging.info("⏰ Iniciando varredura automática de regulações...")
    try:
        resp = await asyncio.to_thread(
            lambda: supabase.table("AlertaSUS_2.0").select("*").execute()
        )
        dados_regulacoes = getattr(resp, "data", []) or []

        for reg in dados_regulacoes:
            chat_id = reg.get("chat_id")
            numero_reg = str(reg.get("numero_reg", "")).strip()
            status_anterior = str(reg.get("status_anterior", "") or "").strip()
            nome_paciente = reg.get("nome_paciente", "Não informado")

            if not chat_id or not numero_reg:
                continue

            try:
                resultado = await consultar_status_fms(numero_reg)
                if resultado.get("sucesso"):
                    status_atual = str(resultado.get("status_resumido", "")).strip()

                    if status_anterior and status_atual != status_anterior:
                        await asyncio.to_thread(
                            lambda: supabase.table("AlertaSUS_2.0").update({
                                "status_anterior": status_atual
                            }).eq("chat_id", int(chat_id)).eq("numero_reg", str(numero_reg)).execute()
                        )

                        msg_alerta = (
                            f"🚨 <b>ALERTA DE ATUALIZAÇÃO!</b>\n\n"
                            f"📋 <b>Regulação:</b> <code>{escape(numero_reg)}</code>\n"
                            f"👤 <b>Paciente:</b> {escape(str(nome_paciente))}\n\n"
                            f"📊 <b>Novo Status:</b>\n{escape(status_atual)}"
                        )
                        await app.bot.send_message(
                            chat_id=int(chat_id),
                            text=msg_alerta,
                            parse_mode="HTML"
                        )
                        logging.info(f"Alerta enviado para Chat ID {chat_id} (Reg: {numero_reg})")
                    
                    elif not status_anterior:
                        await asyncio.to_thread(
                            lambda: supabase.table("AlertaSUS_2.0").update({
                                "status_anterior": status_atual
                            }).eq("chat_id", int(chat_id)).eq("numero_reg", str(numero_reg)).execute()
                        )

            except Exception as err_item:
                logging.error(f"Erro ao verificar regulação {numero_reg}: {err_item}")

    except Exception as e:
        logging.error(f"Erro geral na varredura automática: {e}")

# ==========================================
# 10. FUNÇÕES LEGADAS (COMPATIBILIDADE)
# ==========================================
async def abrir_link_cadastro(update, context):
    """Função legada para compatibilidade de importação com main.py."""
    pass