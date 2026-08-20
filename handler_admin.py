import os
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import ContextTypes
from database import supabase

# Leitura dos IDs de administradores
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

from config import ADMIN_ID
from functools import wraps

def eh_admin(func):
    @wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id != ADMIN_ID:
            await update.message.reply_text("⛔ Acesso negado: você não é um administrador.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

@eh_admin
async def comando_conceder_cortesia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Comando restrito para administradores.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ Uso correto: `/cortesia <TELEGRAM_ID>`", parse_mode="Markdown")
        return

    target_id = context.args[0].strip()

    try:
        # Insere ou atualiza o status para o target_id fornecido
        supabase.table("assinaturas").upsert({
            "chat_id": str(target_id),
            "tipo_plano": "cortesia",
            "limite_ids": 99,
            "status": "ativo",
            "data_inicio": datetime.now(timezone.utc).isoformat(),
            "data_vencimento": None
        }, on_conflict="chat_id").execute()

        await update.message.reply_text(
            f"✅ **CONFIRMAÇÃO DE CORTESIA**\n\n"
            f"• **Usuário Ativado:** `{target_id}`\n"
            f"• **Plano:** Cortesia (Ilimitado)\n"
            f"• **Status no Banco:** Ativo",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao registrar no banco: {e}")

    except Exception as e:
        print(f"[ADMIN] ❌ Erro no Supabase: {e}")
        await update.message.reply_text(f"❌ Erro ao registrar no banco de dados: {e}")
        return

    # 4. Notificação para o usuário contemplado (se for um ID diferente do seu)
    if str(target_id) != str(admin_chat_id):
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=(
                    "🎁 <b>Você recebeu um acesso Cortesia!</b>\n\n"
                    "Sua conta no <b>AlertaSUS 2.0</b> foi atualizada para acesso gratuito e ilimitado."
                ),
                parse_mode="HTML"
            )
        except Exception as err:
            print(f"[ADMIN] ⚠️ Não foi possível notificar o usuário {target_id}: {err}")


async def comando_remover_cortesia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Comando restrito para administradores.")
        return

    if not context.args:
        await update.message.reply_text(
            "⚠️ <b>Uso correto:</b> <code>/remover_cortesia <TELEGRAM_ID></code>", 
            parse_mode="HTML"
        )
        return

    try:
        target_id = context.args[0].strip()
        int(target_id)
    except ValueError:
        await update.message.reply_text("❌ ID do Telegram inválido.")
        return

    try:
        supabase.table("assinaturas").update({
            "status": "expirado"
        }).eq("chat_id", str(target_id)).execute()

        await context.bot.send_message(
            chat_id=admin_chat_id,
            text=f"🔴 <b>CONFIRMAÇÃO:</b> Cortesia revogada para o ID <code>{target_id}</code>.",
            parse_mode="HTML"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao revogar cortesia: {e}")