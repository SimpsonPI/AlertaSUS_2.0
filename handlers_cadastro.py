# handlers_cadastro.py
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

async def iniciar_cadastro_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "📝 <b>Iniciando cadastro de nova regulação.</b>\n\n"
        "Por favor, digite o <b>número do Cartão SUS</b> do paciente (15 dígitos):",
        parse_mode="HTML", reply_markup=TECLADO_CANCELAR
    )
    return ETAPA_SUS

async def receber_sus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context): return ConversationHandler.END
    sus = re.sub(r"\D", "", update.message.text)
    if len(sus) != 15:
        await update.message.reply_text("⚠️ O Cartão SUS deve conter exatamente 15 dígitos. Tente novamente:")
        return ETAPA_SUS
    context.user_data["sus"] = sus
    await update.message.reply_text("Qual o <b>nome completo</b> do paciente?", parse_mode="HTML")
    return ETAPA_NOME

async def receber_nome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context): return ConversationHandler.END
    context.user_data["nome"] = update.message.text.strip()
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
    context.user_data["procedimento"] = update.message.text.strip()

    teclado_lgpd = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Aceitar e Finalizar", callback_data="aceitar_lgpd")],
        [InlineKeyboardButton("❌ Cancelar Cadastro", callback_data="cancelar_cadastro")]
    ])

    await update.message.reply_text(
        "🛡️ <b>TERMO DE CONSENTIMENTO LGPD</b>\n\n"
        "Para prosseguir com o monitoramento automático, autorizo o armazenamento dos dados fornecidos exclusivamente para finalidades de consulta pública no sistema FMS Piauí.\n\n"
        f"{DISCLAIMER_TEXTO}\n\nVocê aceita o termo?",
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

    dados_salvar = {
        "id_do_chat": user_id,
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