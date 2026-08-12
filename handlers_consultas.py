# handlers_consultas.py
import logging
import re
from html import escape
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from scraper import consultar_status_fms
from database import (
    buscar_regulacoes_por_chat_id as buscar_regulacoes_por_usuario,
    obter_regulacao_por_numero
)
from utils import (
    DISCLAIMER_TEXTO, TECLADO_MENU, TECLADO_CANCELAR, CONSULTAR_ID,
    _extrair_id_e_nome, mascarar_nome, _montar_msg_html, verificar_se_e_menu_e_executar
)

logger = logging.getLogger(__name__)

async def _buscar_regulacao_por_id_reg(numero_reg: str):
    try:
        res = obter_regulacao_por_numero(numero_reg)
        return await res if hasattr(res, "__await__") else res
    except Exception as e:
        logger.error(f"Erro ao buscar regulação {numero_reg}: {e}")
        return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data.clear()
    mensagem = (
        f"Olá, <b>{escape(user.first_name)}</b>! 👋\n\n"
        f"Bem-vindo ao <b>AlertaSUS 2.0</b>.\n"
        f"Eu ajudo você a acompanhar o status de suas regulações na FMS Piauí em tempo real.\n\n"
        f"{DISCLAIMER_TEXTO}\n\nEscolha uma opção no menu abaixo para começar:"
    )
    await update.message.reply_text(mensagem, parse_mode="HTML", reply_markup=TECLADO_MENU)

async def comando_ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensagem = (
        "ℹ️ <b>AJUDA E INSTRUÇÕES DE USO</b>\n\n"
        "<b>📋 Verificar Todas:</b> Consulta o status de todas as regulações que você cadastrou.\n"
        "<b>🔍 Verificar Específico:</b> Permite selecionar ou digitar o ID de uma regulação para verificar individualmente.\n"
        "<b>➕ Cadastrar Nova:</b> Cadastra uma nova regulação para monitoramento contínuo.\n"
        "<b>✏️ Corrigir ID:</b> Altera informações de um cadastro existente.\n"
        "<b>🗑️ Excluir Regulação:</b> Remove uma regulação da sua lista de monitoramento.\n\n"
        f"{DISCLAIMER_TEXTO}\n\n"
        "<i>Se precisar cancelar qualquer operação, clique em '🚫 Cancelar Operação' ou digite /cancelar.</i>"
    )
    await update.message.reply_text(mensagem, parse_mode="HTML", reply_markup=TECLADO_MENU)

async def cancelar_operacao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ Operação cancelada com sucesso.", reply_markup=TECLADO_MENU)
    return ConversationHandler.END

async def comando_verificar_todas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    regulacoes = buscar_regulacoes_por_usuario(user_id)
    if hasattr(regulacoes, "__await__"): regulacoes = await regulacoes

    if not regulacoes:
        await update.message.reply_text(
            "ℹ️ <b>Você não possui nenhuma regulação cadastrada.</b>\nUtilize a opção <b>➕ Cadastrar Nova</b> para cadastrar.",
            parse_mode="HTML", reply_markup=TECLADO_MENU
        )
        return

    msg_inicial = await update.message.reply_text(
        f"🔄 Consultando <b>{len(regulacoes)}</b> regulação(ões) na FMS... Por favor, aguarde.",
        parse_mode="HTML"
    )

    for reg in regulacoes:
        num_reg, _ = _extrair_id_e_nome(reg)
        try:
            resultado = await consultar_status_fms(num_reg)
        except Exception as e:
            logger.error(f"Erro FMS {num_reg}: {e}")
            resultado = {"sucesso": False}

        msg_html = _montar_msg_html(num_reg, resultado, reg)
        await update.message.reply_text(msg_html, parse_mode="HTML")

    try: await msg_inicial.delete()
    except Exception: pass

    await update.message.reply_text("✅ Consulta concluída!", reply_markup=TECLADO_MENU)

async def iniciar_verificar_especifico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        regulacoes = buscar_regulacoes_por_usuario(user_id)
        if hasattr(regulacoes, "__await__"): regulacoes = await regulacoes

        if not regulacoes:
            msg_sem_dados = "⚠️ Nenhuma regulação cadastrada encontrada para o seu usuário."
            if update.message: await update.message.reply_text(msg_sem_dados, reply_markup=TECLADO_MENU)
            elif update.callback_query: await update.callback_query.message.reply_text(msg_sem_dados, reply_markup=TECLADO_MENU)
            return ConversationHandler.END

        teclado_botoes = []
        for reg in regulacoes:
            num_reg, nome_bruto = _extrair_id_e_nome(reg)
            teclado_botoes.append([InlineKeyboardButton(f"📄 {num_reg} - {mascarar_nome(nome_bruto)}", callback_data=f"ver_esp_{num_reg}")])

        teclado_botoes.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_ver_esp")])
        reply_markup = InlineKeyboardMarkup(teclado_botoes)

        msg = "🔍 <b>Selecione qual regulação deseja verificar:</b>\n<i>Ou se preferir, digite o número do ID da regulação abaixo:</i>"
        if update.message: await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode="HTML")
        elif update.callback_query: await update.callback_query.message.reply_text(msg, reply_markup=reply_markup, parse_mode="HTML")

        return CONSULTAR_ID
    except Exception as e:
        logger.error(f"Erro em iniciar_verificar_especifico: {e}")
        return ConversationHandler.END

async def processar_verificar_especifico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        num_reg = None

        if query:
            await query.answer()
            data = query.data
            if data == "cancelar_ver_esp":
                await query.edit_message_text("❌ Consulta cancelada.")
                await query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)
                return ConversationHandler.END
            if data.startswith("ver_esp_"):
                num_reg = data.replace("ver_esp_", "").strip()

        elif update.message and update.message.text:
            if await verificar_se_e_menu_e_executar(update, context):
                return ConversationHandler.END
            num_reg = re.sub(r"\D", "", update.message.text.strip())

        if not num_reg:
            msg_erro = "⚠️ Não foi possível identificar o ID da regulação. Digite apenas os números:"
            if query: await query.edit_message_text(msg_erro)
            else: await update.message.reply_text(msg_erro, reply_markup=TECLADO_CANCELAR)
            return CONSULTAR_ID

        msg_espera = f"⌛ <b>Consultando a regulação</b> <code>{escape(num_reg)}</code> na FMS..."
        if query: await query.edit_message_text(msg_espera, parse_mode="HTML")
        else: msg_status = await update.message.reply_text(msg_espera, parse_mode="HTML")

        reg_db = await _buscar_regulacao_por_id_reg(num_reg)
        try: resultado = await consultar_status_fms(num_reg)
        except Exception: resultado = {"sucesso": False}

        msg_html = _montar_msg_html(num_reg, resultado, reg_db)

        if query:
            await query.message.reply_text(msg_html, parse_mode="HTML", reply_markup=TECLADO_MENU)
        else:
            try: await msg_status.delete()
            except Exception: pass
            await update.message.reply_text(msg_html, parse_mode="HTML", reply_markup=TECLADO_MENU)

        context.user_data.clear()
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Erro em processar_verificar_especifico: {e}")
        return ConversationHandler.END