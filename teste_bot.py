import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

load_dotenv()
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

async def responder_tudo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_recebido = update.message.text
    chat_id = update.effective_chat.id
    print(f"\n📩 [MENSAGEM CHEGOU!] Chat ID: {chat_id} | Texto: {texto_recebido}", flush=True)
    await update.message.reply_text(f"Recebi sua mensagem: {texto_recebido}")

print("🚀 Iniciando robô de teste...", flush=True)
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(MessageHandler(filters.ALL, responder_tudo))
app.run_polling()