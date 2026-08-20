# Importe a função de validação do seu arquivo (ex: handler.py)
from handler import usuario_tem_acesso

def test_regra_cortesia():
    # Simula usuário cortesia mesmo com status desatualizado
    user_data = {"tipo_plano": "cortesia", "status": "inativo"}
    assert usuario_tem_acesso(user_data) is True

def test_regra_degustacao():
    # Simula usuário degustação ativo
    user_data = {"tipo_plano": "degustacao", "usou_degustacao": True}
    assert usuario_tem_acesso(user_data) is Truepytest test_planos.py

    # Dentro da função gerar_pagamento_pix em handler_pagamento.py:

        payment = result["response"]
        point_of_interaction = payment.get("point_of_interaction", {})
        transaction_data = point_of_interaction.get("transaction_data", {})
        
        pix_copia_cola = transaction_data.get("qr_code")
        qr_code_base64 = transaction_data.get("qr_code_base64")
        mp_payment_id = payment.get("id")

        # TRAVA DE SEGURANÇA: Se a API do gateway não retornar o código Pix válido
        if not pix_copia_cola:
            logger.error(f"❌ Resposta do Mercado Pago sem qr_code válido para user {user_id}")
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ Não foi possível gerar o código Pix no momento. Por favor, tente novamente em instantes."
            )
            return