import os
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import ContextTypes
from database import supabase

# Leitura dos IDs de administradores
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]


async def comando_conceder_cortesia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 👇 LOGS DE DIAGNÓSTICO
    print("--------------------------------------------------")
    print(f"🚨 COMANDO RECEBIDO DO USUÁRIO: {update.effective_user.id}")
    print(f"📋 ADMINS PERMITIDOS NO CÓDIGO: {ADMIN_IDS}")
    print("--------------------------------------------------")

    admin_chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    # ... resto do código igual ...

    # 1. Trava de segurança para administradores
    if user_id not in ADMIN_IDS:
        print(f"[ADMIN] ❌ Acesso negado para o ID {user_id}")
        await update.message.reply_text("⛔ Comando restrito para administradores.")
        return

    # 2. Validação dos argumentos
    if not context.args:
        await update.message.reply_text(
            "⚠️ <b>Uso correto:</b> <code>/conceder_cortesia <TELEGRAM_ID></code>", 
            parse_mode="HTML"
        )
        return

    try:
        target_id = context.args[0].strip()
        int(target_id)
    except ValueError:
        await update.message.reply_text("❌ ID do Telegram inválido. Informe apenas números.")
        return

    agora = datetime.now(timezone.utc)

    # 3. Gravação na tabela public.assinaturas no Supabase
    try:
        supabase.table("assinaturas").upsert({
            "chat_id": str(target_id),
            "tipo_plano": "cortesia",
            "limite_ids": 99,
            "status": "ativo",
            "data_inicio": agora.isoformat(),
            "data_vencimento": None
        }, on_conflict="chat_id").execute()

        print(f"[ADMIN] ✅ Cortesia gravada no Supabase para: {target_id}")

        # Mensagem de CONFIRMAÇÃO direta para você (Admin)
        await context.bot.send_message(
            chat_id=admin_chat_id,
            text=(
                f"✅ <b>CONFIRMAÇÃO DE CORTESIA</b>\n\n"
                f"• <b>Usuário Ativado:</b> <code>{target_id}</code>\n"
                f"• <b>Plano:</b> Cortesia (Ilimitado)\n"
                f"• <b>Status no Banco:</b> Ativo"
            ),
            parse_mode="HTML"
        )

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