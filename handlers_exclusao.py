from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database import buscar_regulacoes_por_chat_id, deletar_regulacao_por_id

from handlers.utils import (
    SELECIONAR_REGULACAO_EXCLUIR, CONFIRMAR_EXCLUSAO
)

async def iniciar_excluir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        chat_id = update.effective_chat.id
        regulacoes = buscar_regulacoes_por_chat_id(chat_id)

        if not regulacoes:
            mensagem = "⚠️ **Nenhuma regulação encontrada para o seu ID de chat.**"
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.edit_message_text(mensagem, parse_mode="Markdown")
            else:
                await update.message.reply_text(mensagem, parse_mode="Markdown")
            return ConversationHandler.END

        keyboard = []
        for reg in regulacoes:
            num_reg = reg.get("numero_reg", "N/A")
            nome_completo = reg.get("nome_paciente", "").strip()

            partes = nome_completo.split()
            if partes:
                primeiro_nome = partes[0].upper()
                iniciais_sobrenomes = [f"{p[0].upper()}." for p in partes[1:] if p]
                nome_formatado = f"{primeiro_nome} {' '.join(iniciais_sobrenomes)}".strip()
            else:
                nome_formatado = "Paciente"

            texto_botao = f"🗑️ Regulação {num_reg} - {nome_formatado}"
            keyboard.append([InlineKeyboardButton(texto_botao, callback_data=f"excluir_sel_{num_reg}")])

        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_excluir")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        texto = "❌ **Exclusão de Regulação**\n\nClique na regulação que deseja excluir:"

        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(texto, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            await update.message.reply_text(texto, reply_markup=reply_markup, parse_mode="Markdown")

        return SELECIONAR_REGULACAO_EXCLUIR

    except Exception as e:
        print(f"ERRO em iniciar_excluir: {e}", flush=True)
        if update.message:
            await update.message.reply_text(f"⚠️ Ocorreu um erro ao carregar as regulações: `{e}`", parse_mode="Markdown")
        return ConversationHandler.END

async def selecionar_regulacao_excluir_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancelar_excluir":
        await query.edit_message_text("❌ **Operação cancelada.**", parse_mode="Markdown")
        return ConversationHandler.END

    num_reg = query.data.replace("excluir_sel_", "")
    context.user_data["regulacao_para_excluir"] = num_reg

    keyboard = [
        [InlineKeyboardButton("✅ Confirmar Exclusão", callback_data="confirmar_exclusao")],
        [InlineKeyboardButton("🚫 Cancelar", callback_data="cancelar_excluir")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    texto = (
        f"⚠️ **Atenção!**\n\n"
        f"Tem certeza que deseja excluir a regulação **{num_reg}**?\n"
        f"Esta ação não poderá ser desfeita."
    )

    await query.edit_message_text(texto, reply_markup=reply_markup, parse_mode="Markdown")
    return CONFIRMAR_EXCLUSAO

async def confirmar_exclusao_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancelar_excluir":
        await query.edit_message_text("❌ **Operação cancelada.**", parse_mode="Markdown")
        return ConversationHandler.END

    chat_id = update.effective_chat.id
    num_reg = context.user_data.get("regulacao_para_excluir")

    if not num_reg:
        await query.edit_message_text("⚠️ **Erro ao identificar a regulação.** Operação cancelada.")
        return ConversationHandler.END

    sucesso = deletar_regulacao_por_id(chat_id, num_reg)

    if sucesso:
        await query.edit_message_text(f"✅ **Regulação {num_reg} excluída com sucesso!**", parse_mode="Markdown")
    else:
        await query.edit_message_text(f"❌ **Erro ao excluir a regulação {num_reg}.** Tente novamente.", parse_mode="Markdown")

    context.user_data.clear()
    return ConversationHandler.END

async def cancelar_excluir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("❌ **Operação cancelada.**", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ **Operação cancelada.**", parse_mode="Markdown")
    
    context.user_data.clear()
    return ConversationHandler.END