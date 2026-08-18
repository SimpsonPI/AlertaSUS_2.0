from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import verificar_assinatura, iniciar_degustacao

async def comando_planos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe os planos com botões para seleção baseada no status do usuário."""
    chat_id = update.effective_chat.id
    assinatura = await verificar_assinatura(chat_id)
    
    mensagem = "💎 <b>Escolha o seu plano AlertaSUS 2.0:</b>"
    keyboard = []
    
    # Exibe Degustação apenas se o usuário nunca assinou nada
    if assinatura is None:
        keyboard.append([InlineKeyboardButton("🟢 Degustação (7 dias grátis)", callback_data="plano_free")])
    
    keyboard.extend([
        [InlineKeyboardButton("🔵 Essencial (R$ 9,90)", callback_data="plano_essencial")],
        [InlineKeyboardButton("🟣 Pro (R$ 14,99)", callback_data="plano_pro")],
        [InlineKeyboardButton("💬 Falar com Comercial", url="https://wa.me/86994083113")]
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.message.edit_text(mensagem, parse_mode="HTML", reply_markup=reply_markup)
    else:
        await update.message.reply_text(mensagem, parse_mode="HTML", reply_markup=reply_markup)

async def processar_selecao_plano(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa o clique no botão do plano."""
    query = update.callback_query
    await query.answer()
    
    chat_id = update.effective_chat.id
    escolha = query.data
    
    if escolha == "plano_free":
        sucesso = await iniciar_degustacao(chat_id)
        if sucesso:
            mensagem = "✅ <b>Degustação ativada com sucesso!</b>\n\nVocê tem 7 dias de acesso gratuito."
        else:
            mensagem = "❌ Erro ao ativar degustação. Tente novamente."
    else:
        mapa_planos = {
            "plano_essencial": "Essencial (R$ 9,90)",
            "plano_pro": "Pro (R$ 14,99)"
        }
        plano_nome = mapa_planos.get(escolha, "Desconhecido")
        mensagem = (
            f"✅ Você selecionou o plano: <b>{plano_nome}</b>\n\n"
            "Clique no botão abaixo para realizar o pagamento:"
        )
    
    # Botão de pagamento
    keyboard = [[InlineKeyboardButton("💳 Pagar Agora", url="https://link-de-pagamento-aqui")]]
    
    await query.edit_message_text(
        mensagem,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
