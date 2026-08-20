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
        last_name = query.from_user.last_name or "AlertaSUS"
        plano_chave = query.data.replace("pix_", "")
        chat_id = query.message.chat_id
    else:
        user_id = update.effective_user.id
        first_name = update.effective_user.first_name or "Usuario"
        last_name = update.effective_user.last_name or "AlertaSUS"
        plano_chave = context.args[0].lower() if context.args else "pro_mensal"
        chat_id = update.effective_chat.id

    detalhes_plano = PLANOS.get(plano_chave, PLANOS["pro_mensal"])
    nome_plano = detalhes_plano["nome"]
    valor = detalhes_plano["valor"]

    payment_data = {
        "transaction_amount": float(valor),
        "description": f"AlertaSUS 2.0 - {nome_plano}",
        "payment_method_id": "pix",
        "payer": {
            "email": f"cliente_{user_id}@gmail.com",
            "first_name": first_name,
            "last_name": last_name
        },
        "external_reference": str(user_id)
    }

    try:
        result = sdk.payment().create(payment_data)
        
        print("--------------------------------------------------")
        print("LOG MERCADO PAGO STATUS CODE:", result.get("status"))
        print("LOG MERCADO PAGO RESPONSE:", result.get("response"))
        print("--------------------------------------------------")
        
        if result.get("status") not in [200, 201]:
            erro_mp = result.get("response", {})
            print("❌ ERRO DETALHADO DO MERCADO PAGO:", erro_mp.get("message"), erro_mp.get("cause"))
            await context.bot.send_message(chat_id=chat_id, text="❌ Erro ao gerar o pagamento no Mercado Pago. Tente novamente em instantes.")
            return

        # Acesso seguro utilizando .get() em sub-dicionários
        payment = result.get("response", {})
        point_of_interaction = payment.get("point_of_interaction", {})
        transaction_data = point_of_interaction.get("transaction_data", {})
        
        pix_copia_cola = transaction_data.get("qr_code")
        qr_code_base64 = transaction_data.get("qr_code_base64")
        mp_payment_id = payment.get("id")

        # TRAVA DE SEGURANÇA 1: Validação de presença do código Pix Copia e Cola
        if not pix_copia_cola or not mp_payment_id:
            print("❌ ERRO DE SEGURANÇA: Resposta do Mercado Pago sem qr_code ou ID válido.")
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ Não foi possível recuperar os dados do Pix. Por favor, tente novamente em instantes."
            )
            return

        # TRAVA DE SEGURANÇA 2: Isolamento do registro no Supabase
        try:
            supabase.table("pagamentos_pix").insert({
                "chat_id": str(user_id),
                "pix_id": str(mp_payment_id),
                "valor": float(valor),
                "tipo_plano": plano_chave,
                "status": "pending"
            }).execute()
        except Exception as e_db:
            print(f"⚠️ AVISO: Erro ao registrar pagamento na tabela pagamentos_pix: {e_db}")

        legenda_mensagem = (
            f"💳 <b>{nome_plano.upper()} - AlertaSUS 2.0</b>\n\n"
            f"• Valor: R$ {valor:.2f}\n"
            f"• Liberação: Instantânea após a confirmação\n\n"
            f"Aponte a câmera do seu banco para o QR Code acima ou utilize o código Copia e Cola abaixo:"
        )

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

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"`{pix_copia_cola}`",
            parse_mode="Markdown"
        )

    except Exception as e:
        print(f"❌ EXCEÇÃO AO GERAR PIX: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Ocorreu um erro inesperado ao gerar a cobrança Pix. Tente novamente em instantes."
        )