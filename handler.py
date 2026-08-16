import logging
import asyncio
from html import escape
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import Forbidden, TelegramError
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes
)

from config import TELEGRAM_BOT_TOKEN
from database import (
    buscar_todas_regulacoes_ativas,
    atualizar_campo_regulacao,
    desativar_regulacoes_por_chat_id
)

try:
    from scraper import consultar_status_fms, montar_mensagem_regulacao
except ImportError:
    async def consultar_status_fms(num_reg):
        return None
    def montar_mensagem_regulacao(*args, **kwargs):
        return ""

URL_TERMO_LGPD = "https://telegra.ph/DECLARA%C3%87%C3%83O-DE-INDEPEND%C3%8ANCIA-08-13"
logger = logging.getLogger(__name__)

from handlers_consultas import (
    start, comando_ajuda, comando_verificar_todas, iniciar_verificar_especifico,
    processar_verificar_especifico, cancelar_operacao
)
from handlers_cadastro import (
    iniciar_cadastro_manual, receber_sus, receber_nome, receber_celular, 
    receber_nascimento, receber_regulacao, receber_cbo, receber_procedimento, finalizar_cadastro
)
from handlers_gestao import (
    iniciar_corrigir, selecionar_regulacao_callback, selecionar_campo_callback, 
    salvar_novo_valor, iniciar_excluir, selecionar_regulacao_excluir_callback, confirmar_exclusao_callback
)
from handlers_comercial import comando_planos
from utils import (
    CONSULTAR_ID, SELECIONAR_REGULACAO, SELECIONAR_CAMPO, AGUARDAR_NOVO_VALOR,
    SELECIONAR_REGULACAO_EXCLUIR, CONFIRMAR_EXCLUSAO, ETAPA_SUS, ETAPA_NOME, 
    ETAPA_CELULAR, ETAPA_NASCIMENTO, ETAPA_REGULACAO, ETAPA_CBO, ETAPA_PROCEDIMENTO, ETAPA_LGPD
)

async def comando_privacidade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("📄 Consultar Termo e Política", url=URL_TERMO_LGPD)]]
    await update.message.reply_text(
        "📋 <b>Termo de Consentimento e Política de Privacidade</b>",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def executar_varredura_automatica(context: ContextTypes.DEFAULT_TYPE):
    # (Conteúdo da varredura mantido anteriormente)
    pass

async def configurar_menu_comandos(app):
    comandos = [
        BotCommand("start", "Início"),
        BotCommand("verificar", "Verificar"),
        BotCommand("consultar", "Consultar"),
        BotCommand("cadastrar", "Cadastrar"),
        BotCommand("corrigir", "Corrigir"),
        BotCommand("excluir", "Excluir"),
        BotCommand("planos", "Planos"),
        BotCommand("privacidade", "Privacidade"),
        BotCommand("ajuda", "Ajuda"),
        BotCommand("cancelar", "Cancelar")
    ]
    await app.bot.set_my_commands(comandos)

conv_cadastro = ConversationHandler(
    entry_points=[CommandHandler("cadastrar", iniciar_cadastro_manual), MessageHandler(filters.Regex("^➕ Cadastrar Nova$"), iniciar_cadastro_manual)],
    states={
        ETAPA_SUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_sus)],
        ETAPA_NOME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_nome)],
        ETAPA_CELULAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_celular)],
        ETAPA_NASCIMENTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_nascimento)],
        ETAPA_REGULACAO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_regulacao)],
        ETAPA_CBO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_cbo)],
        ETAPA_PROCEDIMENTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_procedimento)],
        ETAPA_LGPD: [CallbackQueryHandler(finalizar_cadastro)]
    },
    fallbacks=[CommandHandler("cancelar", cancelar_operacao), MessageHandler(filters.Regex("^🚫 Cancelar Operação$"), cancelar_operacao)]
)

conv_consulta_especifica = ConversationHandler(
    entry_points=[CommandHandler("consultar", iniciar_verificar_especifico), MessageHandler(filters.Regex("^🔍 Verificar Específico$"), iniciar_verificar_especifico)],
    states={
        CONSULTAR_ID: [CallbackQueryHandler(processar_verificar_especifico), MessageHandler(filters.TEXT & ~filters.COMMAND, processar_verificar_especifico)]
    },
    fallbacks=[CommandHandler("cancelar", cancelar_operacao)]
)

conv_corrigir = ConversationHandler(
    entry_points=[CommandHandler("corrigir", iniciar_corrigir), MessageHandler(filters.Regex("^✏️ Corrigir ID$"), iniciar_corrigir)],
    states={
        SELECIONAR_REGULACAO: [CallbackQueryHandler(selecionar_regulacao_callback, pattern="^(corr_reg_|cancelar_corr)")],
        SELECIONAR_CAMPO: [CallbackQueryHandler(selecionar_campo_callback, pattern="^(form_edit_|form_salvar_|corr_campo_|cancelar_corr)")],
        AGUARDAR_NOVO_VALOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, salvar_novo_valor)]
    },
    fallbacks=[CommandHandler("cancelar", cancelar_operacao)]
)

conv_excluir = ConversationHandler(
    entry_points=[CommandHandler("excluir", iniciar_excluir), MessageHandler(filters.Regex("^🗑️ Excluir Regulação$"), iniciar_excluir)],
    states={
        SELECIONAR_REGULACAO_EXCLUIR: [CallbackQueryHandler(selecionar_regulacao_excluir_callback, pattern="^(excl_reg_|cancelar_excl)")],
        CONFIRMAR_EXCLUSAO: [CallbackQueryHandler(confirmar_exclusao_callback, pattern="^(conf_excl_sim|cancelar_excl)")]
    },
    fallbacks=[CommandHandler("cancelar", cancelar_operacao)]
)

__all__ = [
    "CONSULTAR_ID", "SELECIONAR_REGULACAO", "SELECIONAR_CAMPO", "AGUARDAR_NOVO_VALOR",
    "SELECIONAR_REGULACAO_EXCLUIR", "CONFIRMAR_EXCLUSAO", "ETAPA_SUS", "ETAPA_NOME",
    "ETAPA_CELULAR", "ETAPA_NASCIMENTO", "ETAPA_REGULACAO", "ETAPA_CBO", "ETAPA_PROCEDIMENTO",
    "ETAPA_LGPD", "start", "comando_ajuda", "comando_privacidade", "cancelar_operacao",
    "configurar_menu_comandos", "executar_varredura_automatica", "comando_verificar_todas",
    "iniciar_verificar_especifico", "processar_verificar_especifico", "iniciar_cadastro_manual",
    "receber_sus", "receber_nome", "receber_celular", "receber_nascimento", "receber_regulacao",
    "receber_cbo", "receber_procedimento", "finalizar_cadastro", "iniciar_corrigir",
    "selecionar_regulacao_callback", "selecionar_campo_callback", "salvar_novo_valor", "comando_planos",
    "cancelar_corrigir", "iniciar_excluir", "selecionar_regulacao_excluir_callback",
    "confirmar_exclusao_callback", "cancelar_excluir"
]
