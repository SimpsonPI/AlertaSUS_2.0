import logging
import re
from html import escape
from datetime import datetime

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand
)
from telegram.ext import (
    ContextTypes,
    ConversationHandler
)

# Tenta importar do config, com fallback para padrão se não existir
try:
    from config import VARREDURA_INTERVALO_MINUTOS
except ImportError:
    VARREDURA_INTERVALO_MINUTOS = 30

# Importação do Banco de Dados com fallback de segurança
try:
    from database import (
        buscar_regulacoes_por_chat_id as buscar_regulacoes_por_usuario,
        salvar_regulacao,
        atualizar_campo_regulacao,
        excluir_regulacao_db,
        obter_regulacao_por_id,
        obter_regulacao_por_numero,
        registrar_consentimento_lgpd
    )
except ImportError:
    from database import *

# Busca flexível da função de varredura
try:
    from database import buscar_todas_regulacoes_ativas
except ImportError:
    try:
        from database import obter_todas_regulacoes as buscar_todas_regulacoes_ativas
    except ImportError:
        async def buscar_todas_regulacoes_ativas():
            return []

from scraper import consultar_status_fms

# Configuração de Logging Unificada
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --------------------------------------------------
# ESTADOS DAS CONVERSAÇÕES
# --------------------------------------------------

# Consulta Específica
CONSULTAR_ID = 1

# Correção
SELECIONAR_REGULACAO = 10
SELECIONAR_CAMPO = 11
AGUARDAR_NOVO_VALOR = 12

# Exclusão
SELECIONAR_REGULACAO_EXCLUIR = 20
CONFIRMAR_EXCLUSAO = 21

# Cadastro Manual
ETAPA_SUS = 30
ETAPA_NOME = 31
ETAPA_CELULAR = 32
ETAPA_NASCIMENTO = 33
ETAPA_REGULACAO = 34
ETAPA_CBO = 35
ETAPA_PROCEDIMENTO = 36
ETAPA_LGPD = 37

# --------------------------------------------------
# TECLADOS
# --------------------------------------------------

TECLADO_MENU = ReplyKeyboardMarkup(
    [
        ["📋 Verificar Todas", "🔍 Verificar Específico"],
        ["➕ Cadastrar Nova", "✏️ Corrigir ID"],
        ["🗑️ Excluir Regulação", "ℹ️ Ajuda"]
    ],
    resize_keyboard=True
)

TECLADO_CANCELAR = ReplyKeyboardMarkup(
    [["🚫 Cancelar Operação"]],
    resize_keyboard=True
)

# --------------------------------------------------
# FUNÇÕES AUXILIARES E FORMATADORES
# --------------------------------------------------

def _extrair_id_e_nome(reg: dict):
    """Extrai o número da regulação (numero_reg) e o nome do paciente."""
    # Busca direta priorizando 'numero_reg' e 'num_reg'
    num_id = (
        reg.get("numero_reg") or 
        reg.get("num_reg") or 
        reg.get("numero_regulacao") or 
        reg.get("numero_solicitacao") or 
        reg.get("id_regulacao") or 
        reg.get("id")
    )
    
    nome = (
        reg.get("nome_paciente") or 
        reg.get("paciente") or 
        reg.get("nome") or 
        "Paciente não informado"
    )
    
    return str(num_id), str(nome)

# --------------------------------------------------
# HANDLERS BASE E COMANDOS DIRECTOS
# --------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o bot e apresenta o menu principal."""
    user = update.effective_user
    context.user_data.clear()
    
    mensagem = (
        f"Olá, <b>{escape(user.first_name)}</b>! 👋\n\n"
        f"Bem-vindo ao <b>AlertaSUS 2.0</b>.\n"
        f"Eu ajudo você a acompanhar o status de suas regulações na FMS Piauí em tempo real.\n\n"
        f"Escolha uma opção no menu abaixo para começar:"
    )
    await update.message.reply_text(mensagem, parse_mode="HTML", reply_markup=TECLADO_MENU)

async def comando_ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe o guia de ajuda e uso do sistema."""
    mensagem = (
        "ℹ️ <b>AJUDA E INSTRUÇÕES DE USO</b>\n\n"
        "<b>📋 Verificar Todas:</b> Consulta o status de todas as regulações que você cadastrou.\n"
        "<b>🔍 Verificar Específico:</b> Permite selecionar ou digitar o ID de uma regulação para verificar individualmente.\n"
        "<b>➕ Cadastrar Nova:</b> Cadastra uma nova regulação para monitoramento contínuo.\n"
        "<b>✏️ Corrigir ID:</b> Altera informações de um cadastro existente.\n"
        "<b>🗑️ Excluir Regulação:</b> Remove uma regulação da sua lista de monitoramento.\n\n"
        "<i>Se precisar cancelar qualquer operação, clique em '🚫 Cancelar Operação' ou digite /cancelar.</i>"
    )
    await update.message.reply_text(mensagem, parse_mode="HTML", reply_markup=TECLADO_MENU)

async def cancelar_operacao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancela a operação atual e retorna ao menu principal."""
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Operação cancelada com sucesso.",
        reply_markup=TECLADO_MENU
    )
    return ConversationHandler.END

# --------------------------------------------------
# FLUXO DE CONSULTA (VERIFICAR TODAS / ESPECÍFICO)
# --------------------------------------------------

async def comando_verificar_todas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verifica todas as regulações cadastradas pelo usuário."""
    user_id = update.effective_user.id
    regulacoes = buscar_regulacoes_por_usuario(user_id)

    if not regulacoes:
        await update.message.reply_text(
            "ℹ️ <b>Você não possui nenhuma regulação cadastrada.</b>\n"
            "Utilize a opção <b>➕ Cadastrar Nova</b> para cadastrar.",
            parse_mode="HTML",
            reply_markup=TECLADO_MENU
        )
        return

    msg_inicial = await update.message.reply_text(
        f"🔄 Consultando <b>{len(regulacoes)}</b> regulação(ões) na FMS... Por favor, aguarde.",
        parse_mode="HTML"
    )

    for reg in regulacoes:
        num_reg, _ = _extrair_id_e_nome(reg)
        resultado = await consultar_status_fms(num_reg)
        
        if resultado.get("sucesso"):
            msg_html = _montar_msg_html(num_reg, resultado, reg)
            await update.message.reply_text(msg_html, parse_mode="HTML")
        else:
            msg_erro = resultado.get("mensagem") or "Erro ao consultar FMS."
            await update.message.reply_text(
                f"⚠️ <b>ID {num_reg}:</b> {escape(msg_erro)}",
                parse_mode="HTML"
            )

    await msg_inicial.delete()
    await update.message.reply_text("✅ Consulta concluída!", reply_markup=TECLADO_MENU)

async def iniciar_verificar_especifico(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Inicia a consulta de uma regulação específica apresentando botões inline."""
    user_id = update.effective_user.id
    regulacoes = buscar_regulacoes_por_usuario(user_id)

    if not regulacoes:
        await update.message.reply_text(
            "⚠️ <b>Você não possui nenhuma regulação cadastrada.</b>\n\n"
            "Utilize a opção <b>➕ Cadastrar Nova</b> no menu principal.",
            parse_mode="HTML",
            reply_markup=TECLADO_MENU
        )
        return ConversationHandler.END

    teclado_inline = []
    for r in regulacoes:
        num, nome = _extrair_id_e_nome(r)
        # Trocado 'ID:' por 'Regulação:' no botão
        teclado_inline.append([InlineKeyboardButton(f"📄 Regulação: {num} - {nome}", callback_data=f"ver_esp_{num}")])

    teclado_inline.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_ver_esp")])

    await update.message.reply_text(
        "🔎 <b>Selecione uma regulação abaixo ou digite o número da regulação desejada:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(teclado_inline)
    )
    return CONSULTAR_ID

async def processar_verificar_especifico(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Processa o número da regulação escolhido via botão Inline ou digitado manualmente."""
    query = update.callback_query

    # 1. Entrada via Botão Inline
    if query:
        await query.answer()

        if query.data == "cancelar_ver_esp":
            await query.edit_message_text("❌ Operação de consulta cancelada.")
            await query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)
            context.user_data.clear()
            return ConversationHandler.END

        numero_reg = query.data.replace("ver_esp_", "")
        await query.edit_message_text(
            f"🔎 Consultando Regulação <code>{escape(numero_reg)}</code> na FMS...", 
            parse_mode="HTML"
        )

    # 2. Entrada via Texto Digitado
    else:
        if await verificar_se_e_menu_e_executar(update, context):
            return ConversationHandler.END

        texto = update.message.text.strip()
        numero_reg = re.sub(r"\D", "", texto)

        if not numero_reg:
            await update.message.reply_text(
                "⚠️ Por favor, digite apenas os números da regulação:", 
                reply_markup=TECLADO_CANCELAR
            )
            return CONSULTAR_ID

        msg_espera = await update.message.reply_text(
            f"🔎 Pesquisando Regulação <code>{escape(numero_reg)}</code>...", 
            parse_mode="HTML"
        )

    # 3. Lógica de consulta (banco de dados e FMS)
    reg_db = await _buscar_regulacao_por_id_reg(numero_reg)
    resultado = await consultar_status_fms(numero_reg)

    if query:
        if resultado.get("sucesso"):
            msg_html = _montar_msg_html(numero_reg, resultado, reg_db)
            await query.edit_message_text(msg_html, parse_mode="HTML")
        else:
            msg_erro = resultado.get("mensagem") or "Regulação não encontrada na FMS."
            await query.edit_message_text(f"❌ {escape(msg_erro)}", parse_mode="HTML")
        await query.message.reply_text("O que deseja fazer agora?", reply_markup=TECLADO_MENU)
    else:
        await msg_espera.delete()
        if resultado.get("sucesso"):
            msg_html = _montar_msg_html(numero_reg, resultado, reg_db)
            await update.message.reply_text(msg_html, parse_mode="HTML", reply_markup=TECLADO_MENU)
        else:
            msg_erro = resultado.get("mensagem") or "Regulação não encontrada na FMS."
            await update.message.reply_text(f"❌ {escape(msg_erro)}", parse_mode="HTML", reply_markup=TECLADO_MENU)

    context.user_data.clear()
    return ConversationHandler.END

    # 3. Lógica de consulta (banco de dados e FMS)
    reg_db = await _buscar_regulacao_por_id_reg(numero_reg)
    resultado = await consultar_status_fms(numero_reg)

    if query:
        if resultado.get("sucesso"):
            msg_html = _montar_msg_html(numero_reg, resultado, reg_db)
            await query.edit_message_text(msg_html, parse_mode="HTML")
        else:
            msg_erro = resultado.get("mensagem") or "Regulação não encontrada na FMS."
            await query.edit_message_text(f"❌ {escape(msg_erro)}", parse_mode="HTML")
        await query.message.reply_text("O que deseja fazer agora?", reply_markup=TECLADO_MENU)
    else:
        await msg_espera.delete()
        if resultado.get("sucesso"):
            msg_html = _montar_msg_html(numero_reg, resultado, reg_db)
            await update.message.reply_text(msg_html, parse_mode="HTML", reply_markup=TECLADO_MENU)
        else:
            msg_erro = resultado.get("mensagem") or "Regulação não encontrada na FMS."
            await update.message.reply_text(f"❌ {escape(msg_erro)}", parse_mode="HTML", reply_markup=TECLADO_MENU)

    context.user_data.clear()
    return ConversationHandler.END

# --------------------------------------------------
# FLUXO DE CADASTRO MANUAL
# --------------------------------------------------

async def iniciar_cadastro_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Inicia a sequência de perguntas para cadastro de nova regulação."""
    context.user_data.clear()
    await update.message.reply_text(
        "📝 <b>Iniciando cadastro de nova regulação.</b>\n\n"
        "Por favor, digite o <b>número do Cartão SUS</b> do paciente (15 dígitos):",
        parse_mode="HTML",
        reply_markup=TECLADO_CANCELAR
    )
    return ETAPA_SUS

async def receber_sus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    sus = re.sub(r"\D", "", update.message.text)
    if len(sus) != 15:
        await update.message.reply_text("⚠️ O Cartão SUS deve conter exatamente 15 dígitos. Tente novamente:")
        return ETAPA_SUS

    context.user_data["sus"] = sus
    await update.message.reply_text("Qual o <b>nome completo</b> do paciente?", parse_mode="HTML")
    return ETAPA_NOME

async def receber_nome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    context.user_data["nome"] = update.message.text.strip()
    await update.message.reply_text("Informe o <b>número do celular/WhatsApp</b> (com DDD):", parse_mode="HTML")
    return ETAPA_CELULAR

async def receber_celular(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    celular = re.sub(r"\D", "", update.message.text)
    if len(celular) < 10:
        await update.message.reply_text("⚠️ Número inválido. Digite o DDD + Número (ex: 86999998888):")
        return ETAPA_CELULAR

    context.user_data["celular"] = celular
    await update.message.reply_text("Qual a <b>data de nascimento</b> do paciente? (DD/MM/AAAA):", parse_mode="HTML")
    return ETAPA_NASCIMENTO

async def receber_nascimento(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    data_str = update.message.text.strip()
    try:
        data_valida = datetime.strptime(data_str, "%d/%m/%Y").strftime("%Y-%m-%d")
        context.user_data["nascimento"] = data_valida
    except ValueError:
        await update.message.reply_text("⚠️ Formato de data inválido! Digite no formato <b>DD/MM/AAAA</b>:", parse_mode="HTML")
        return ETAPA_NASCIMENTO

    await update.message.reply_text("Digite o <b>número do ID da Regulação</b> (apenas números):", parse_mode="HTML")
    return ETAPA_REGULACAO

async def receber_regulacao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    num_reg = re.sub(r"\D", "", update.message.text)
    if not num_reg:
        await update.message.reply_text("⚠️ Digite um número de regulação válido:")
        return ETAPA_REGULACAO

    context.user_data["numero_regulacao"] = num_reg
    await update.message.reply_text("Informe o código <b>CBO</b> da especialidade (opcional - digite 0 para pular):", parse_mode="HTML")
    return ETAPA_CBO

async def receber_cbo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    cbo = update.message.text.strip()
    context.user_data["cbo"] = cbo if cbo != "0" else ""
    await update.message.reply_text("Qual a descrição do <b>Procedimento/Exame</b>?", parse_mode="HTML")
    return ETAPA_PROCEDIMENTO

async def receber_procedimento(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    context.user_data["procedimento"] = update.message.text.strip()

    teclado_lgpd = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Aceitar e Finalizar", callback_data="aceitar_lgpd")],
        [InlineKeyboardButton("❌ Cancelar Cadastro", callback_data="cancelar_cadastro")]
    ])

    await update.message.reply_text(
        "🛡️ <b>TERMO DE CONSENTIMENTO LGPD</b>\n\n"
        "Para prosseguir com o monitoramento automático, autorizo o armazenamento dos dados fornecidos exclusivamente para finalidades de consulta pública no sistema FMS Piauí.\n\n"
        "Você aceita o termo?",
        parse_mode="HTML",
        reply_markup=teclado_lgpd
    )
    return ETAPA_LGPD

async def finalizar_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancelar_cadastro":
        await query.edit_message_text("❌ Cadastro cancelado pelo usuário.")
        await query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)
        context.user_data.clear()
        return ConversationHandler.END

    user_id = update.effective_user.id
    dados = context.user_data

    dados_salvar = {
        "telegram_id": user_id,
        "cartao_sus": dados.get("sus"),
        "nome_paciente": dados.get("nome"),
        "celular": dados.get("celular"),
        "data_nascimento": dados.get("nascimento"),
        "numero_regulacao": dados.get("numero_regulacao"),
        "cbo": dados.get("cbo"),
        "procedimento": dados.get("procedimento")
    }

    sucesso = await salvar_regulacao(dados_salvar)
    await registrar_consentimento_lgpd(user_id, aceito=True)

    if sucesso:
        await query.edit_message_text("✅ <b>Regulação cadastrada com sucesso!</b>\nEla será monitorada automaticamente pelo sistema.", parse_mode="HTML")
    else:
        await query.edit_message_text("❌ Ocorreu um erro ao salvar a regulação no banco de dados. Tente novamente mais tarde.")

    await query.message.reply_text("O que deseja fazer agora?", reply_markup=TECLADO_MENU)
    context.user_data.clear()
    return ConversationHandler.END

# --------------------------------------------------
# FLUXO DE CORREÇÃO
# --------------------------------------------------

async def iniciar_corrigir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    regulacoes = buscar_regulacoes_por_usuario(user_id)

    if not regulacoes:
        await update.message.reply_text("⚠️ Você não possui regulações cadastradas para corrigir.", reply_markup=TECLADO_MENU)
        return ConversationHandler.END

    teclado = []
    for r in regulacoes:
        num, nome = _extrair_id_e_nome(r)
        db_id = r.get("id") or r.get("id_regulacao") or num
        teclado.append([InlineKeyboardButton(f"📄 Reg: {num} - {nome}", callback_data=f"corr_reg_{db_id}")])
    teclado.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_corr")])

    await update.message.reply_text("✏️ <b>Selecione qual regulação deseja corrigir:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(teclado))
    return SELECIONAR_REGULACAO

async def selecionar_regulacao_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancelar_corr":
        await query.edit_message_text("❌ Operação de correção cancelada.")
        await query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)
        return ConversationHandler.END

    reg_id = query.data.replace("corr_reg_", "")
    context.user_data["corr_reg_id"] = reg_id

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("Cartão SUS", callback_data="corr_campo_cartao_sus"), InlineKeyboardButton("Nome", callback_data="corr_campo_nome_paciente")],
        [InlineKeyboardButton("Celular", callback_data="corr_campo_celular"), InlineKeyboardButton("Nascimento", callback_data="corr_campo_data_nascimento")],
        [InlineKeyboardButton("Nº Regulação", callback_data="corr_campo_numero_regulacao"), InlineKeyboardButton("Procedimento", callback_data="corr_campo_procedimento")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_corr")]
    ])

    await query.edit_message_text("Selecione qual campo você deseja alterar:", reply_markup=teclado)
    return SELECIONAR_CAMPO

async def selecionar_campo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancelar_corr":
        await query.edit_message_text("❌ Operação de correção cancelada.")
        await query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)
        return ConversationHandler.END

    campo = query.data.replace("corr_campo_", "")
    context.user_data["corr_campo"] = campo

    await query.edit_message_text(f"Digite o novo valor para <b>{campo.replace('_', ' ').title()}</b>:", parse_mode="HTML")
    return AGUARDAR_NOVO_VALOR

async def salvar_novo_valor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    novo_valor = update.message.text.strip()
    reg_id = context.user_data.get("corr_reg_id")
    campo = context.user_data.get("corr_campo")

    sucesso = await atualizar_campo_regulacao(reg_id, campo, novo_valor)

    if sucesso:
        await update.message.reply_text("✅ Campo atualizado com sucesso!", reply_markup=TECLADO_MENU)
    else:
        await update.message.reply_text("❌ Falha ao atualizar o registro no banco de dados.", reply_markup=TECLADO_MENU)

    context.user_data.clear()
    return ConversationHandler.END

async def cancelar_corrigir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await cancelar_operacao(update, context)

# --------------------------------------------------
# FLUXO DE EXCLUSÃO
# --------------------------------------------------

async def iniciar_excluir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    regulacoes = buscar_regulacoes_por_usuario(user_id)

    if not regulacoes:
        await update.message.reply_text("⚠️ Você não possui nenhuma regulação cadastrada para excluir.", reply_markup=TECLADO_MENU)
        return ConversationHandler.END

    teclado = []
    for r in regulacoes:
        num, nome = _extrair_id_e_nome(r)
        db_id = r.get("id") or r.get("id_regulacao") or num
        teclado.append([InlineKeyboardButton(f"🗑️ Reg: {num} - {nome}", callback_data=f"excl_reg_{db_id}")])
    teclado.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_excl")])

    await update.message.reply_text("🗑️ <b>Selecione qual regulação deseja excluir:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(teclado))
    return SELECIONAR_REGULACAO_EXCLUIR

async def selecionar_regulacao_excluir_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancelar_excl":
        await query.edit_message_text("❌ Operação de exclusão cancelada.")
        await query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)
        return ConversationHandler.END

    reg_id = query.data.replace("excl_reg_", "")
    context.user_data["excl_reg_id"] = reg_id

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚠️ Sim, Excluir", callback_data="conf_excl_sim")],
        [InlineKeyboardButton("❌ Não, Cancelar", callback_data="cancelar_excl")]
    ])

    await query.edit_message_text("<b>Tem certeza que deseja excluir esta regulação do monitoramento?</b>\nEsta ação não poderá ser desfeita.", parse_mode="HTML", reply_markup=teclado)
    return CONFIRMAR_EXCLUSAO

async def confirmar_exclusao_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "conf_excl_sim":
        reg_id = context.user_data.get("excl_reg_id")
        sucesso = await excluir_regulacao_db(reg_id)

        if sucesso:
            await query.edit_message_text("✅ Regulação excluída com sucesso!")
        else:
            await query.edit_message_text("❌ Ocorreu um erro ao tentar excluir a regulação.")
    else:
        await query.edit_message_text("❌ Exclusão cancelada.")

    await query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)
    context.user_data.clear()
    return ConversationHandler.END

async def cancelar_excluir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await cancelar_operacao(update, context)

# --------------------------------------------------
# VARREDURA AUTOMÁTICA EM BACKGROUND
# --------------------------------------------------

async def executar_varredura_automatica(context: ContextTypes.DEFAULT_TYPE):
    """Executa a verificação periódica de todas as regulações cadastradas e notifica mudanças."""
    logger.info("🤖 Iniciando varredura automática de regulações...")
    regulacoes = await buscar_todas_regulacoes_ativas()

    for reg in regulacoes:
        num_reg, _ = _extrair_id_e_nome(reg)
        telegram_id = reg.get("telegram_id")
        status_antigo = reg.get("status_atual")

        resultado = await consultar_status_fms(num_reg)

        if resultado.get("sucesso"):
            novo_status = resultado.get("status")
            if novo_status and novo_status != status_antigo:
                reg_db_id = reg.get("id") or reg.get("id_regulacao")
                if reg_db_id:
                    await atualizar_campo_regulacao(reg_db_id, "status_atual", novo_status)
                
                msg_notificacao = (
                    f"🔔 <b>MUDANÇA DE STATUS DETECTADA!</b>\n\n"
                    f"{_montar_msg_html(num_reg, resultado, reg)}"
                )
                try:
                    await context.bot.send_message(chat_id=telegram_id, text=msg_notificacao, parse_mode="HTML")
                except Exception as e:
                    logger.error(f"Erro ao enviar notificação para {telegram_id}: {e}")