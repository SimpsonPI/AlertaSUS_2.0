import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler
)

logger = logging.getLogger(__name__)

# DEFINIÇÃO DOS ESTADOS DO CONVERSATIONHANDLER
AGUARDANDO_MENSAGEM = 1

# ID do Administrador para receber os chamados (Substitua se necessário)
ADMIN_CHAT_ID = 5242040324


async def menu_suporte(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe o menu de opções da Central de Ajuda."""
    mensagem = update.message or (update.callback_query.message if update.callback_query else None)
    if not mensagem:
        return

    teclado = [
        [InlineKeyboardButton("🛠️ Resolução de Problemas / FAQ", callback_data="sup_faq")],
        [InlineKeyboardButton("👤 Falar com Atendente Humano", callback_data="sup_humano")],
        [InlineKeyboardButton("❌ Fechar", callback_data="sup_fechar")]
    ]

    await mensagem.reply_text(
        "❓ <b>Central de Ajuda e Suporte</b>\n\n"
        "Como podemos te ajudar hoje? Selecione uma das opções abaixo:",
        reply_markup=InlineKeyboardMarkup(teclado),
        parse_mode="HTML"
    )


async def callback_suporte(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa os cliques nos botões do menu de suporte."""
    query = update.callback_query
    await query.answer()

    if query.data == "sup_faq":
        texto_faq = (
            "🛠️ <b>Perguntas Frequentes (FAQ)</b>\n\n"
            "1. <b>Como cadastrar uma regulação?</b>\n"
            "Clique em /cadastrar_nova no menu e digite o Cartão SUS (15 dígitos).\n\n"
            "2. <b>Como corrigir dados?</b>\n"
            "Utilize o comando /corrigir para selecionar o registro desejado.\n\n"
            "3. <b>Onde vejo minhas consultas?</b>\n"
            "Utilize /verificar_todos para listar todas as regulações cadastradas."
        )
        await query.message.reply_text(texto_faq, parse_mode="HTML")
        return ConversationHandler.END

    elif query.data == "sup_humano":
        await query.message.reply_text(
            "📝 <b>Atendimento Humano</b>\n\n"
            "Por favor, digite detalhadamente a sua dúvida ou o problema que está enfrentando.\n"
            "<i>(Sua mensagem será enviada diretamente à nossa equipe de suporte)</i>",
            parse_mode="HTML"
        )
        return AGUARDANDO_MENSAGEM

    elif query.data == "sup_fechar":
        await query.message.delete()
        return ConversationHandler.END


async def receber_mensagem_suporte(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe a mensagem enviada pelo usuário e encaminha para o Administrador."""
    if not update.message or not update.message.text:
        return AGUARDANDO_MENSAGEM

    user = update.effective_user
    texto_usuario = update.message.text

    # Envia notificação ao Admin
    mensagem_admin = (
        f"📩 <b>NOVO CHAMADO DE SUPORTE</b>\n\n"
        f"<b>Usuário:</b> {user.full_name} (@{user.username or 'sem_username'})\n"
        f"<b>ID do Usuário:</b> <code>{user.id}</code>\n\n"
        f"<b>Mensagem:</b>\n{texto_usuario}\n\n"
        f"👉 <i>Para responder, use:</i> <code>/responder {user.id} Sua resposta aqui</code>"
    )

    try:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=mensagem_admin, parse_mode="HTML")
        await update.message.reply_text(
            "✅ <b>Chamado enviado com sucesso!</b>\n\n"
            "Sua mensagem foi entregue à nossa equipe. Responderemos em breve diretamente aqui no bot.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Erro ao enviar suporte para admin: {e}")
        await update.message.reply_text("❌ Ocorreu um erro ao enviar sua mensagem. Tente novamente mais tarde.")

    return ConversationHandler.END


async def responder_chamado_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Permite ao administrador responder um chamado via /responder <ID> <mensagem>."""
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⚠️ Comando exclusivo para administradores.")
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ <b>Formato incorreto!</b>\n\n"
            "Use: <code>/responder ID_DO_USUARIO Sua resposta aqui</code>",
            parse_mode="HTML"
        )
        return

    user_id_destino = context.args[0]
    mensagem_resposta = " ".join(context.args[1:])

    try:
        await context.bot.send_message(
            chat_id=int(user_id_destino),
            text=(
                "🎧 <b>Resposta da Equipe de Suporte:</b>\n\n"
                f"{mensagem_resposta}"
            ),
            parse_mode="HTML"
        )
        await update.message.reply_text("✅ <b>Resposta enviada com sucesso ao usuário!</b>", parse_mode="HTML")
    except Exception as e:
        logger.error(f"Erro ao responder chamado: {e}")
        await update.message.reply_text(f"❌ Falha ao enviar mensagem: {e}")


async def cancelar_suporte(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela o atendimento de suporte."""
    await update.message.reply_text("❌ Atendimento cancelado.")
    return ConversationHandler.END


# Aliases para compatibilidade com importações antigas do main.py
iniciar_abertura_chamado = menu_suporte
processar_faq_suporte = callback_suporte

# CONFIGURAÇÃO DO CONVERSATION HANDLER DO SUPORTE
conv_suporte = ConversationHandler(
    entry_points=[
        CommandHandler("ajuda", menu_suporte),
        CommandHandler("suporte", menu_suporte),
        CallbackQueryHandler(callback_suporte, pattern="^sup_")
    ],
    states={
        AGUARDANDO_MENSAGEM: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receber_mensagem_suporte)
        ]
    },
    fallbacks=[CommandHandler("cancelar", cancelar_suporte)]
)