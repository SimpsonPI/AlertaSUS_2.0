import re
import asyncio
import logging
import traceback
from html import escape
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from rate_limiter import rate_limit
from scraper import consultar_status_fms

from handlers.utils import (
    CONSULTAR_ID, TECLADO_MENU, TECLADO_CANCELAR,
    mascarar_nome, _montar_msg_html,
    _buscar_regulacao_por_id_reg, _buscar_regulacoes_db
)
from handlers.base import verificar_se_e_menu_e_executar

@rate_limit(max_mensagens=5, janela_segundos=60)
async def comando_verificar_todas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    chat_id = update.effective_chat.id
    msg_espera = await update.message.reply_text("🔍 <b>Consultando suas regulações no sistema...</b>", parse_mode="HTML")

    try:
        regulacoes = await _buscar_regulacoes_db(chat_id)
        if not regulacoes:
            await msg_espera.edit_text(
                "ℹ️ Você não possui nenhuma regulação cadastrada.\nUtilize a opção <b>➕ Cadastrar Nova</b> para cadastrar.",
                parse_mode="HTML"
            )
            return ConversationHandler.END

        await msg_espera.delete()

        for reg in regulacoes:
            numero_reg = str(reg.get("numero_reg", "")).strip()
            if not numero_reg:
                continue

            try:
                resultado = await consultar_status_fms(numero_reg)
                if resultado.get("sucesso"):
                    msg_html = _montar_msg_html(numero_reg, resultado, reg)
                    await update.message.reply_text(msg_html, parse_mode="HTML")
                else:
                    msg_erro = resultado.get("mensagem") or "Não foi possível consultar esta regulação."
                    await update.message.reply_text(
                        f"⚠️ <b>ID {escape(numero_reg)}:</b> {escape(msg_erro)}",
                        parse_mode="HTML"
                    )
            except Exception as item_err:
                logging.error(f"Erro ao processar regulação {numero_reg}: {item_err}")

            await asyncio.sleep(4)

    except Exception as e:
        logging.error(f"Erro ao consultar regulações: {traceback.format_exc()}")
        await msg_espera.edit_text("❌ Ocorreu um erro ao acessar o banco de dados. Tente novamente em instantes.")

    return ConversationHandler.END

@rate_limit(max_mensagens=5, janela_segundos=60)
async def iniciar_verificar_especifico(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Exibe lista de IDs cadastrados em botões Inline para consulta individual rápida."""
    context.user_data.clear()
    chat_id = update.effective_chat.id
    regulacoes = await _buscar_regulacoes_db(chat_id)

    if not regulacoes:
        mensagem = "⚠️ <b>Você não possui nenhuma regulação cadastrada.</b>\nUtilize a opção <b>➕ Cadastrar Nova</b> no menu principal."
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(mensagem, parse_mode="HTML")
        else:
            await update.message.reply_text(mensagem, parse_mode="HTML", reply_markup=TECLADO_MENU)
        return ConversationHandler.END

    teclado = []
    for reg in regulacoes:
        num_reg = str(reg.get("numero_reg", "")).strip()
        nome = mascarar_nome(str(reg.get("nome_paciente", "Não informado")))
        texto_botao = f"🆔 {num_reg} - {nome}"
        teclado.append([InlineKeyboardButton(texto_botao, callback_data=f"ver_esp_{num_reg}")])

    teclado.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_ver_esp")])
    reply_markup = InlineKeyboardMarkup(teclado)

    texto = "🔍 <b>Verificar Regulação Específica</b>\n\nSelecione abaixo qual ID você deseja consultar:"

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(texto, reply_markup=reply_markup, parse_mode="HTML")
    else:
        await update.message.reply_text(texto, reply_markup=reply_markup, parse_mode="HTML")

    return CONSULTAR_ID

async def processar_verificar_especifico(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Processa o ID escolhido via botão Inline ou digitado manualmente."""
    query = update.callback_query

    # 1. Entrada via botão Inline
    if query:
        await query.answer()

        if query.data == "cancelar_ver_esp":
            await query.edit_message_text("❌ Operação de consulta cancelada.")
            await query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)
            context.user_data.clear()
            return ConversationHandler.END

        numero_reg = query.data.replace("ver_esp_", "")
        await query.edit_message_text(
            f"🔎 Consultando ID <code>{escape(numero_reg)}</code> na FMS...", 
            parse_mode="HTML"
        )

    # 2. Entrada via texto
    else:
        if await verificar_se_e_menu_e_executar(update, context):
            return ConversationHandler.END

        texto = update.message.text.strip()
        numero_reg = re.sub(r"\D", "", texto)

        if not numero_reg:
            await update.message.reply_text(
                "⚠️ Por favor, digite apenas os números do ID da regulação:", 
                reply_markup=TECLADO_CANCELAR
            )
            return CONSULTAR_ID

        msg_espera = await update.message.reply_text(
            f"🔎 Pesquisando ID <code>{escape(numero_reg)}</code>...", 
            parse_mode="HTML"
        )

    # 3. Lógica de consulta
    reg_db = await _buscar_regulacao_por_id_reg(numero_reg)
    resultado = await consultar_status_fms(numero_reg)

    if query:
        if resultado.get("sucesso"):
            msg_html = _montar_msg_html(numero_reg, resultado, reg_db)
            await query.edit_message_text(msg_html, parse_mode="HTML")
        else:
            msg_erro = resultado.get("mensagem") or "Regulação não encontrada na FMS."
            await query.edit_message_text(f"❌ {escape(msg_erro)}", parse_mode="HTML")
        await query.message.reply_text("O que deseja fazer agora?", reply_markup=TECLADO_MENU)
    else:
        await msg_espera.delete()
        if resultado.get("sucesso"):
            msg_html = _montar_msg_html(numero_reg, resultado, reg_db)
            await update.message.reply_text(msg_html, parse_mode="HTML", reply_markup=TECLADO_MENU)
        else:
            msg_erro = resultado.get("mensagem") or "Regulação não encontrada na FMS."
            await update.message.reply_text(f"❌ {escape(msg_erro)}", parse_mode="HTML", reply_markup=TECLADO_MENU)

    context.user_data.clear()
    return ConversationHandler.END