import re
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from database import salvar_regulacao, registrar_consentimento_lgpd
from utils import (
    DISCLAIMER_TEXTO, TECLADO_MENU, TECLADO_CANCELAR,
    ETAPA_SUS, ETAPA_NOME, ETAPA_CELULAR, ETAPA_NASCIMENTO,
    ETAPA_REGULACAO, ETAPA_CBO, ETAPA_PROCEDIMENTO, ETAPA_LGPD,
    formatar_data, formatar_celular, verificar_se_e_menu_e_executar
)

# 🔗 Cole aqui o link da página que você publicou no Telegra.ph
URL_TERMO_LGPD = "https://telegra.ph/DECLARA%C3%87%C3%83O-DE-INDEPEND%C3%8ANCIA-08-13"

async def iniciar_cadastro_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "📝 <b>Iniciando cadastro de nova regulação.</b>\n\n"
        "Por favor, digite o <b>número do Cartão SUS</b> do paciente (15 dígitos):",
        parse_mode="HTML", reply_markup=TECLADO_CANCELAR
    )
    return ETAPA_SUS

async def receber_sus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context): 
        return ConversationHandler.END

    sus = re.sub(r"\D", "", update.message.text)
    if len(sus) != 15:
        await update.message.reply_text("⚠️ O Cartão SUS deve conter exatamente 15 dígitos. Tente novamente:")
        return ETAPA_SUS

    context.user_data["sus"] = sus

    # 1. Consulta no Supabase se já existem dados vinculados a este SUS
    paciente_existente = await buscar_paciente_por_sus(sus)

    if paciente_existente:
        # 2. Preenche os dados pessoais automaticamente no contexto
        context.user_data["nome_paciente"] = paciente_existente.get("nome_paciente")
        context.user_data["celular"] = paciente_existente.get("celular")
        context.user_data["data_nascimento"] = paciente_existente.get("data_nascimento")

        # 3. Informa o usuário e pula direto para a etapa do Número da Regulação
        await update.message.reply_text(
            f"👤 <b>Paciente localizado no sistema!</b>\n\n"
            f"• <b>Nome:</b> {context.user_data['nome_paciente']}\n"
            f"• <b>Celular:</b> {context.user_data['celular']}\n"
            f"• <b>Nascimento:</b> {context.user_data['data_nascimento']}\n\n"
            f"Os dados pessoais foram reaproveitados automaticamente.\n\n"
            f"👉 <b>Digite o Número da nova Regulação (ID):</b>",
            parse_mode="HTML"
        )
        return ETAPA_REGULACAO

    # Se for um Cartão SUS novo, segue o fluxo normal pedindo o nome
    await update.message.reply_text("Qual o <b>nome completo</b> do paciente?", parse_mode="HTML")
    return ETAPA_NOME

async def receber_nome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context): return ConversationHandler.END
    context.user_data["nome"] = update.message.text.strip().upper()
    await update.message.reply_text("Informe o <b>número do celular/WhatsApp</b> (com DDD):", parse_mode="HTML")
    return ETAPA_CELULAR

async def receber_celular(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context): return ConversationHandler.END
    celular_raw = update.message.text
    if len(re.sub(r"\D", "", celular_raw)) < 10:
        await update.message.reply_text("⚠️ Número inválido. Digite o DDD + Número (ex: 86999998888):")
        return ETAPA_CELULAR
    context.user_data["celular"] = formatar_celular(celular_raw)
    await update.message.reply_text("Qual a <b>data de nascimento</b> do paciente? (DD/MM/AAAA):", parse_mode="HTML")
    return ETAPA_NASCIMENTO

async def receber_nascimento(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context): return ConversationHandler.END
    data_formatada = formatar_data(update.message.text.strip())
    if len(data_formatada) == 10 and data_formatada.count("-") == 2:
        context.user_data["nascimento"] = data_formatada
    else:
        await update.message.reply_text("⚠️ Formato de data inválido! Digite no formato <b>DD/MM/AAAA</b>:", parse_mode="HTML")
        return ETAPA_NASCIMENTO
    await update.message.reply_text("Digite o <b>número do ID da Regulação</b> (apenas números):", parse_mode="HTML")
    return ETAPA_REGULACAO

async def receber_regulacao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context): return ConversationHandler.END
    num_reg = re.sub(r"\D", "", update.message.text)
    if not num_reg:
        await update.message.reply_text("⚠️ Digite um número de regulação válido:")
        return ETAPA_REGULACAO
    context.user_data["numero_regulacao"] = num_reg
    await update.message.reply_text("Informe o código <b>CBO</b> da especialidade (opcional - digite 0 para pular):", parse_mode="HTML")
    return ETAPA_CBO

async def receber_cbo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context): return ConversationHandler.END
    cbo = update.message.text.strip()
    context.user_data["cbo"] = cbo if cbo != "0" else ""
    await update.message.reply_text("Qual a descrição do <b>Procedimento/Exame</b>?", parse_mode="HTML")
    return ETAPA_PROCEDIMENTO

async def receber_procedimento(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context): return ConversationHandler.END
    context.user_data["procedimento"] = update.message.text.strip().upper()

    teclado_lgpd = InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Ler Termo e Política Completa", url=URL_TERMO_LGPD)],
        [InlineKeyboardButton("✅ Aceitar e Finalizar", callback_data="aceitar_lgpd")],
        [InlineKeyboardButton("❌ Cancelar Cadastro", callback_data="cancelar_cadastro")]
    ])

    texto_lgpd = (
        "🔒 <b>PROTEÇÃO DE SEUS DADOS — TERMO DE CONSENTIMENTO LGPD</b>\n\n"
        "Para prosseguir com o monitoramento automático, precisamos da sua concordância com o tratamento dos seus dados:\n\n"
        "📌 Usamos seus dados <b>apenas</b> para acompanhar sua regulação e enviar notificações 24/7.\n"
        "📌 Notificações são enviadas <b>somente nesta conversa privada</b>.\n"
        "📌 Você pode consultar ou EXCLUIR tudo a qualquer momento.\n"
        "⚠️ <b>Serviço independente:</b> Não temos vínculo oficial com a Prefeitura de Teresina, FMS ou SUS.\n\n"
        "Ao clicar em <b>Aceitar e Finalizar</b>, você confirma que leu e concorda com nosso Termo e Política de Privacidade."
    )

    await update.message.reply_text(
        texto_lgpd,
        parse_mode="HTML", reply_markup=teclado_lgpd
    )
    return ETAPA_LGPD

async def finalizar_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancelar_cadastro":
        await query.edit_message_text("❌ Cadastro cancelado pelo usuário.")
        await query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)
        context.user_data.clear()
        return ConversationHandler.END

    user_id = update.effective_user.id
    dados = context.user_data

    # Dupla compatibilidade de chave do Telegram ID
    dados_salvar = {
        "id_do_chat": user_id,
        "chat_id": user_id,
        "numero_sus": dados.get("sus"),
        "nome_paciente": dados.get("nome"),
        "celular": dados.get("celular"),
        "data_nascimento": dados.get("nascimento"),
        "numero_reg": dados.get("numero_regulacao"),
        "cbo": dados.get("cbo"),
        "procedimento": dados.get("procedimento")
    }

    sucesso = await salvar_regulacao(dados_salvar)
    await registrar_consentimento_lgpd(user_id, aceito=True)

    if sucesso:
        await query.edit_message_text("✅ <b>Regulação cadastrada com sucesso!</b>\nEla será monitorada automaticamente pelo sistema.", parse_mode="HTML")
    else:
        await query.edit_message_text("❌ Ocorreu um erro ao salvar a regulação no Supabase. Tente novamente mais tarde.")

    await query.message.reply_text("O que deseja fazer agora?", reply_markup=TECLADO_MENU)
    context.user_data.clear()
    return ConversationHandler.END