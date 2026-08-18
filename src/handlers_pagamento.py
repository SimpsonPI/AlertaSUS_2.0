import os
import io
import base64
from datetime import datetime
import mercadopago
from telegram import Update
from telegram.ext import ContextTypes
from database import supabase

sdk = mercadopago.SDK(os.getenv("MERCADOPAGO_ACCESS_TOKEN"))

PLANOS = {
    "pro_mensal": {"nome": "Pro Mensal", "valor": 9.90},
    "pro_semestral": {"nome": "Pro Semestral", "valor": 9.99},
    "pro_anual": {"nome": "Pro Anual", "valor": 14.99}
}

async def gerar_pagamento_pix(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if query:
        await query.answer()
        user_id = query.from_user.id
        first_name = query.from_user.first_name or "Usuario"
        plano_chave = query.data.replace("pix_", "")
        chat_id = query.message.chat_id
    else:
        user_id = update.effective_user.id
        first_name = update.effective_user.first_name or "Usuario"
        plano_chave = context.args[0].lower() if context.args else "pro_mensal"
        chat_id = update.effective_chat.id

    detalhes_plano = PLANOS.get(plano_chave, PLANOS["pro_mensal"])
    nome_plano = detalhes_plano["nome"]
    valor = detalhes_plano["valor"]

    payment_data = {
        "transaction_amount": valor,
        "description": f"AlertaSUS 2.0 - {nome_plano}",
        "payment_method_id": "pix",
        "payer": {
            "email": f"user_{user_id}@alertasus.com",
            "first_name": first_name,
        },
        "external_reference": str(user_id)
    }

    try:
        result = sdk.payment().create(payment_data)
        
        if result.get("status") != 201:
            await context.bot.send_message(chat_id=chat_id, text="❌ Erro ao gerar o pagamento no Mercado Pago. Tente novamente em instantes.")
            return

        payment = result["response"]
        transaction_data = payment["point_of_interaction"]["transaction_data"]
        
        pix_copia_cola = transaction_data["qr_code"]
        qr_code_base64 = transaction_data.get("qr_code_base64")
        mp_payment_id = payment["id"]

        # Registra / Atualiza assinatura pendente no Supabase
        supabase.table("assinaturas").upsert({
            "chat_id": str(user_id),
            "tipo_plano": plano_chave,
            "status": "pending",
            "mp_payment_id": str(mp_payment_id),
            "data_vencimento": datetime.utcnow().isoformat()
        }, on_conflict="chat_id").execute()

        legenda_mensagem = (
            f"💳 <b>{nome_plano.upper()} - AlertaSUS 2.0</b>\n\n"
            f"• Valor: R$ {valor:.2f}\n"
            f"• Liberação: Instantânea após a confirmação\n\n"
            f"Aponte a câmera do seu banco para o QR Code acima ou utilize o código Copia e Cola abaixo:"
        )

        # Se houver imagem do QR Code em Base64, converte e envia como foto
        if qr_code_base64:
            img_bytes = base64.b64decode(qr_code_base64)
            img_io = io.BytesIO(img_bytes)
            img_io.name = "qrcode_pix.png"

            await context.bot.send_photo(
                chat_id=chat_id,
                photo=img_io,
                caption=legenda_mensagem,
                parse_mode="HTML"
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=legenda_mensagem,
                parse_mode="HTML"
            )

        # Envia o código Copia e Cola em bloco de texto copiável
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"`{pix_copia_cola}`",
            parse_mode="Markdown"
        )

    except Exception as e:
        print(f"Erro ao processar pagamento Pix: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Ocorreu um erro inesperado ao gerar a cobrança Pix. Tente novamente em instantes."
        )