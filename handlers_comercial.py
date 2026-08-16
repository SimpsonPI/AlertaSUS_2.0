from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

async def comando_planos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe as opções de planos comerciais."""
    mensagem = (
        "💎 <b>Planos AlertaSUS Premium</b>\n\n"
        "Escolha um de nossos planos para obter monitoramento em tempo real, "
        "alertas instantâneos e suporte dedicado:\n\n"
        "• <b>Plano Básico:</b> Monitoramento diário.\n"
        "• <b>Plano Profissional:</b> Monitoramento a cada 1 hora + Notificações WhatsApp.\n"
        "• <b>Plano Enterprise:</b> Monitoramento em tempo real + API exclusiva.\n\n"
        "Clique abaixo para falar com nosso comercial:"
    )
    
    keyboard = [[InlineKeyboardButton("💬 Falar com Comercial", url="https://wa.me/SEU_NUMERO_AQUI")]]
    
    if update.callback_query:
        await update.callback_query.message.edit_text(mensagem, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(mensagem, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
