from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

async def comando_planos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe as opções de planos comerciais."""
    mensagem = (
        "📋 <b>MODELO COMERCIAL - ALERTASUS 2.0</b>\n\n"
        "🟢 <b>DEGUSTAÇÃO (FREE)</b>\n"
        "• Valor: R$ 0,00\n"
        "• Duração: 7 dias\n"
        "• Monitoramento: Até 2 regulações\n\n"
        "🔵 <b>PLANO ESSENCIAL</b>\n"
        "• Valor: R$ 9,90\n"
        "• Duração: 180 dias (Semestral)\n"
        "• Monitoramento: Até 5 regulações\n\n"
        "🟣 <b>PLANO PRO</b>\n"
        "• Valor: R$ 14,99\n"
        "• Duração: 365 dias (Anual)\n"
        "• Monitoramento: Até 9 regulações\n\n"
        "💡 <b>Deseja ativar ou migrar seu plano?</b>\n"
        "Entre em contato com nosso suporte para instruções de liberação."
    )
    
    keyboard = [[InlineKeyboardButton("💬 Falar com Comercial", url="https://wa.me/86994083113")]]
    
    if update.callback_query:
        await update.callback_query.message.edit_text(mensagem, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(mensagem, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
