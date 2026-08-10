import asyncio
import logging
from html import escape
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from rate_limiter import rate_limit
from config import supabase
from scraper import consultar_status_fms

from handlers_utils import (
    SELECIONAR_REGULACAO, SELECIONAR_CAMPO, AGUARDAR_NOVO_VALOR,
    TECLADO_MENU, mascarar_nome, mascarar_sus, para_maiusculo,
    _buscar_regulacoes_db
)
from handlers_base import verificar_se_e_menu_e_executar

@rate_limit(max_mensagens=5, janela_segundos=60)
async def iniciar_corrigir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    chat_id = update.effective_chat.id
    regulacoes = await _buscar_regulacoes_db(chat_id)

    if not regulacoes:
        await update.message.reply_text(
            "⚠️ Você não possui nenhuma regulação cadastrada para corrigir.",
            reply_markup=TECLADO_MENU
        )
        return ConversationHandler.END

    teclado = []
    for reg in regulacoes:
        num_reg = str(reg.get("numero_reg", "")).strip()
        nome = mascarar_nome(str(reg.get("nome_paciente", "Não informado")))
        
        teclado.append([
            InlineKeyboardButton(
                f"📋 Regulação {num_reg} - {nome}", 
                callback_data=f"corr_reg_{num_reg}"
            )
        ])

    teclado.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_corrigir")])

    await update.message.reply_text(
        "✏️ <b>Central de Correção de Dados</b>\n\n"
        "Selecione abaixo qual regulação você deseja alterar:",
        reply_markup=InlineKeyboardMarkup(teclado),
        parse_mode="HTML"
    )
    return SELECIONAR_REGULACAO

async def selecionar_regulacao_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancelar_corrigir":
        await query.edit_message_text("❌ Operação de correção cancelada.")
        await query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)
        context.user_data.clear()
        return ConversationHandler.END

    numero_reg = query.data.replace("corr_reg_", "")
    context.user_data["reg_corrigir"] = numero_reg

    teclado = [
        [InlineKeyboardButton("🆔 Número da Regulação", callback_data="corr_campo_numero_reg")],
        [InlineKeyboardButton("👤 Nome do Paciente", callback_data="corr_campo_nome_paciente")],
        [InlineKeyboardButton("💳 Cartão SUS", callback_data="corr_campo_numero_sus")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_corrigir")]
    ]

    await query.edit_message_text(
        f"📋 Regulação selecionada: <code>{escape(numero_reg)}</code>\n\n"
        f"<b>Qual informação você deseja alterar?</b>",
        reply_markup=InlineKeyboardMarkup(teclado),
        parse_mode="HTML"
    )
    return SELECIONAR_CAMPO

async def selecionar_campo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancelar_corrigir":
        await query.edit_message_text("❌ Operação de correção cancelada.")
        await query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)
        context.user_data.clear()
        return ConversationHandler.END

    campo = query.data.replace("corr_campo_", "")
    context.user_data["campo_corrigir"] = campo

    mural_campos = {
        "numero_reg": ("Número da Regulação", "digite o novo número da regulação (apenas números)"),
        "nome_paciente": ("Nome do Paciente", "digite o nome completo do paciente"),
        "numero_sus": ("Cartão SUS", "digite o novo número do Cartão SUS (15 dígitos)")
    }

    nome_amigavel, instrucao = mural_campos.get(campo, ("Campo", "digite o novo valor"))

    await query.edit_message_text(
        f"✏️ <b>Alterando: {nome_amigavel}</b>\n\n"
        f"Por favor, {instrucao}:",
        parse_mode="HTML"
    )
    return AGUARDAR_NOVO_VALOR

async def salvar_novo_valor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    novo_valor = update.message.text.strip()
    campo = context.user_data.get("campo_corrigir")
    numero_reg_antigo = context.user_data.get("reg_corrigir")
    chat_id = update.effective_chat.id

    if campo == "nome_paciente":
        novo_valor = para_maiusculo(novo_valor)

    if campo in ["numero_reg", "numero_sus"] and not novo_valor.isdigit():
        await update.message.reply_text("⚠️ O valor digitado deve conter apenas números. Tente novamente:")
        return AGUARDAR_NOVO_VALOR

    if campo == "numero_sus" and len(novo_valor) != 15:
        await update.message.reply_text("⚠️ O Cartão SUS deve possuir exatamente 15 dígitos. Tente novamente:")
        return AGUARDAR_NOVO_VALOR

    try:
        dados_atualizacao = {campo: novo_valor}

        if campo == "numero_reg":
            resultado_fms = await consultar_status_fms(novo_valor)
            novo_status = resultado_fms.get("status_resumido", "Atualizado") if resultado_fms.get("sucesso") else "Atualizado"
            dados_atualizacao["status_anterior"] = novo_status

        await asyncio.to_thread(
            lambda: supabase.table("AlertaSUS_2.0")
            .update(dados_atualizacao)
            .eq("chat_id", int(chat_id))
            .eq("numero_reg", str(numero_reg_antigo))
            .execute()
        )

        if campo == "nome_paciente":
            exibicao_valor = mascarar_nome(novo_valor)
        elif campo == "numero_sus":
            exibicao_valor = mascarar_sus(novo_valor)
        else:
            exibicao_valor = escape(novo_valor)

        await update.message.reply_text(
            f"✅ <b>Informação atualizada com sucesso!</b>\n\n"
            f"📋 Regulação: <code>{escape(numero_reg_antigo)}</code>\n"
            f"🔄 Novo valor: <b>{exibicao_valor}</b>",
            reply_markup=TECLADO_MENU,
            parse_mode="HTML"
        )

    except Exception as e:
        logging.error(f"Erro ao atualizar registro no Supabase: {e}")
        await update.message.reply_text("❌ Erro ao salvar a alteração no banco de dados. Tente novamente mais tarde.", reply_markup=TECLADO_MENU)

    context.user_data.clear()
    return ConversationHandler.END

async def cancelar_corrigir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ Operação de correção cancelada.", reply_markup=TECLADO_MENU)
    return ConversationHandler.END