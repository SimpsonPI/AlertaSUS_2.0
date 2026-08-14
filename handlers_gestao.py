import logging
from html import escape
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler

from database import (
    buscar_regulacoes_por_chat_id as buscar_regulacoes_por_usuario,
    excluir_regulacao_db,
    atualizar_campo_regulacao
)
from utils import (
    TECLADO_MENU,
    _extrair_id_e_nome,
    mascarar_nome,
    SELECIONAR_REGULACAO,
    SELECIONAR_CAMPO,
    AGUARDAR_NOVO_VALOR,
    SELECIONAR_REGULACAO_EXCLUIR,
    CONFIRMAR_EXCLUSAO
)

logger = logging.getLogger(__name__)

# ==================================================
# FUNÇÕES DE MASCARAMENTO PARA PRIVACIDADE
# ==================================================

def _mascarar_cartao_sus(sus_str):
    if not sus_str or str(sus_str).upper() == "NONE":
        return "Não informado"
    sus_str = str(sus_str).strip()
    if len(sus_str) >= 4:
        return "*" * (len(sus_str) - 4) + sus_str[-4:]
    return "*****"

def _mascarar_celular(cel_str):
    if not cel_str or str(cel_str).upper() == "NONE":
        return "Não informado"
    cel_str = str(cel_str).strip()
    if len(cel_str) >= 4:
        return cel_str[:2] + " *****-" + cel_str[-4:]
    return "(**)"

def _formatar_data_br_mascarada(data_str):
    if not data_str or str(data_str).upper() == "NONE":
        return "Não informado"
    data_str = str(data_str).strip()
    if "-" in data_str:
        partes = data_str.split("T")[0].split("-")
        if len(partes) == 3:
            return f"**/**/{partes[0]}"
    elif "/" in data_str:
        partes = data_str.split("/")
        if len(partes) == 3:
            return f"**/**/{partes[2]}"
    return "**/**/****"


# Helper para exibir o formulário mascarado (sem opção de alterar SUS)
async def _exibir_formulario_edicao(update: Update, context: ContextTypes.DEFAULT_TYPE, editar_mensagem=True):
    num_reg = context.user_data.get("corr_num_reg")
    dados = context.user_data.get("corr_dados_temp", {})

    # Aplicação de Máscaras para Privacidade
    nome_fmt = mascarar_nome(str(dados.get('nome_paciente', '')))
    sus_fmt = _mascarar_cartao_sus(str(dados.get('numero_sus', '')))
    celular_fmt = _mascarar_celular(str(dados.get('celular', '')))
    nasc_fmt = _formatar_data_br_mascarada(str(dados.get('data_nascimento', '')))

    resumo = (
        f"📝 <b>Formulário de Edição - Regulação <code>{escape(str(num_reg))}</code></b>\n"
        f"<i>Os dados estão parcialmente ocultos para sua privacidade.</i>\n\n"
        f"👤 <b>Nome:</b> {escape(nome_fmt)}\n"
        f"💳 <b>Cartão SUS:</b> {escape(sus_fmt)} <i>(Fixo)</i>\n"
        f"📱 <b>Celular:</b> {escape(celular_fmt)}\n"
        f"🎂 <b>Nascimento:</b> {escape(nasc_fmt)}\n"
        f"🏷️ <b>CBO:</b> {escape(str(dados.get('cbo', '')))}\n"
        f"🩺 <b>Procedimento:</b> {escape(str(dados.get('procedimento', '')))}\n\n"
        f"<b>Escolha um campo para alterar:</b>"
    )

    teclado = [
        [InlineKeyboardButton("👤 Alterar Nome", callback_data="form_edit_nome_paciente")],
        [InlineKeyboardButton("📱 Alterar Celular", callback_data="form_edit_celular")],
        [InlineKeyboardButton("🎂 Alterar Nascimento", callback_data="form_edit_data_nascimento")],
        [InlineKeyboardButton("🏷️ Alterar CBO", callback_data="form_edit_cbo")],
        [InlineKeyboardButton("🩺 Alterar Procedimento", callback_data="form_edit_procedimento")],
        [InlineKeyboardButton("💾 SALVAR ALTERAÇÕES", callback_data="form_salvar_tudo")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_corr")]
    ]

    markup = InlineKeyboardMarkup(teclado)

    if editar_mensagem and update.callback_query:
        msg = await update.callback_query.edit_message_text(resumo, parse_mode="HTML", reply_markup=markup)
        context.user_data["corr_msg_id"] = msg.message_id
    else:
        chat_id = update.effective_chat.id
        msg = await context.bot.send_message(chat_id=chat_id, text=resumo, parse_mode="HTML", reply_markup=markup)
        context.user_data["corr_msg_id"] = msg.message_id


# Helper para deletar a mensagem do formulário (Autodestruição de privacidade)
async def _deletar_mensagem_formulario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    msg_id = context.user_data.get("corr_msg_id")
    if msg_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception as e:
            logger.warning(f"Não foi possível deletar a mensagem de edição: {e}")


# ==================================================
# FLUXO DE CORREÇÃO DE REGULAÇÃO
# ==================================================

async def iniciar_corrigir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        user_id = update.effective_user.id
        regulacoes = buscar_regulacoes_por_usuario(user_id)
        if hasattr(regulacoes, "__await__"): 
            regulacoes = await regulacoes

        if not regulacoes:
            await update.message.reply_text(
                "⚠️ Você não possui nenhuma regulação cadastrada para corrigir.",
                reply_markup=TECLADO_MENU
            )
            return ConversationHandler.END

        teclado = []
        for r in regulacoes:
            num, nome, cbo = _extrair_id_e_nome(r)
            cbo_str = f" ({cbo.strip().upper()})" if cbo and str(cbo).strip().upper() not in ["NONE", "N/A", ""] else ""
            rotulo = f"✏️ {num} - {mascarar_nome(nome)}{cbo_str}"

            teclado.append([InlineKeyboardButton(rotulo, callback_data=f"corr_reg_{num}")])

        teclado.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_corr")])

        msg = await update.message.reply_text(
            "✏️ <b>Selecione qual regulação deseja corrigir:</b>",
            reply_markup=InlineKeyboardMarkup(teclado),
            parse_mode="HTML"
        )
        context.user_data["corr_msg_id"] = msg.message_id
        return SELECIONAR_REGULACAO

    except Exception as e:
        logger.error(f"Erro em iniciar_corrigir: {e}")
        return ConversationHandler.END


async def selecionar_regulacao_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancelar_corr":
        await _deletar_mensagem_formulario(update, context)
        await query.message.reply_text("❌ Operação de correção cancelada.", reply_markup=TECLADO_MENU)
        context.user_data.clear()
        return ConversationHandler.END

    num_reg = query.data.replace("corr_reg_", "").strip()
    context.user_data["corr_num_reg"] = num_reg

    user_id = update.effective_user.id
    regulacoes = buscar_regulacoes_por_usuario(user_id)
    if hasattr(regulacoes, "__await__"):
        regulacoes = await regulacoes

    reg_atual = next((
        r for r in regulacoes 
        if str(r.get("numero_reg") or r.get("numero_regulacao") or r.get("id_regulacao") or r.get("id")) == str(num_reg)
    ), {})

    context.user_data["corr_dados_temp"] = {
        "nome_paciente": reg_atual.get("nome_paciente") or "",
        "numero_sus": reg_atual.get("numero_sus") or reg_atual.get("cartao_sus") or "",
        "celular": reg_atual.get("celular") or "",
        "data_nascimento": reg_atual.get("data_nascimento") or "",
        "cbo": reg_atual.get("cbo") or "",
        "procedimento": reg_atual.get("procedimento") or ""
    }

    await _exibir_formulario_edicao(update, context, editar_mensagem=True)
    return SELECIONAR_CAMPO


async def selecionar_campo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "cancelar_corr":
        await _deletar_mensagem_formulario(update, context)
        await query.message.reply_text("❌ Operação de correção cancelada.", reply_markup=TECLADO_MENU)
        context.user_data.clear()
        return ConversationHandler.END

    # BOTÃO SALVAR TUDO: APAGA O FORMULÁRIO E SALVA
    if data == "form_salvar_tudo":
        num_reg = context.user_data.get("corr_num_reg")
        dados_temp = context.user_data.get("corr_dados_temp", {})

        erros = 0
        for campo_db, valor in dados_temp.items():
            try:
                res = atualizar_campo_regulacao(num_reg, campo_db, valor)
                if hasattr(res, "__await__"):
                    await res
            except Exception as e:
                logger.error(f"Erro ao atualizar {campo_db}: {e}")
                erros += 1

        # DELETA A MENSAGEM DO FORMULÁRIO COM OS DADOS DA TELA
        await _deletar_mensagem_formulario(update, context)

        if erros == 0:
            await query.message.reply_text(f"✅ <b>Todas as alterações da regulação <code>{escape(str(num_reg))}</code> foram salvas com sucesso!</b>", parse_mode="HTML", reply_markup=TECLADO_MENU)
        else:
            await query.message.reply_text("⚠️ Algumas alterações podem não ter sido salvas. Verifique o banco de dados.", reply_markup=TECLADO_MENU)

        context.user_data.clear()
        return ConversationHandler.END

    campo_map = {
        "form_edit_nome_paciente": ("nome_paciente", "o **Nome do Paciente**"),
        "form_edit_celular": ("celular", "o **Celular**"),
        "form_edit_data_nascimento": ("data_nascimento", "a **Data de Nascimento** (DD/MM/AAAA)"),
        "form_edit_cbo": ("cbo", "o **CBO / Especialidade**"),
        "form_edit_procedimento": ("procedimento", "o **Procedimento**")
    }

    if data in campo_map:
        campo_db, rotulo = campo_map[data]
        context.user_data["corr_campo_em_edicao"] = campo_db

        await query.edit_message_text(f"✏️ Digite abaixo o novo valor para {rotulo}:", parse_mode="Markdown")
        return AGUARDAR_NOVO_VALOR

    return SELECIONAR_CAMPO


async def salvar_novo_valor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    novo_valor = update.message.text.strip()
    campo_em_edicao = context.user_data.get("corr_campo_em_edicao")

    if campo_em_edicao:
        if campo_em_edicao not in ["celular", "data_nascimento"]:
            novo_valor = novo_valor.upper()

        context.user_data["corr_dados_temp"][campo_em_edicao] = novo_valor

    await _exibir_formulario_edicao(update, context, editar_mensagem=False)
    return SELECIONAR_CAMPO


async def cancelar_corrigir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await _deletar_mensagem_formulario(update, context)
    context.user_data.clear()
    await update.message.reply_text("❌ Operação de correção cancelada.", reply_markup=TECLADO_MENU)
    return ConversationHandler.END


# ==================================================
# FLUXO DE EXCLUSÃO DE REGULAÇÃO
# ==================================================

async def iniciar_excluir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        user_id = update.effective_user.id
        regulacoes = buscar_regulacoes_por_usuario(user_id)
        if hasattr(regulacoes, "__await__"): 
            regulacoes = await regulacoes

        if not regulacoes:
            await update.message.reply_text(
                "⚠️ Você não possui nenhuma regulação cadastrada para excluir.",
                reply_markup=TECLADO_MENU
            )
            return ConversationHandler.END

        teclado = []
        for r in regulacoes:
            db_id = r.get("id") or r.get("id_regulacao") or r.get("numero_regulacao")
            num, nome, cbo = _extrair_id_e_nome(r)
            
            cbo_str = f" ({cbo.strip().upper()})" if cbo and str(cbo).strip().upper() not in ["NONE", "N/A", ""] else ""
            rotulo = f"🗑️ {num} - {mascarar_nome(nome)}{cbo_str}"

            teclado.append([InlineKeyboardButton(rotulo, callback_data=f"excl_reg_{db_id}")])

        teclado.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_excl")])

        await update.message.reply_text(
            "🗑️ <b>Selecione qual regulação deseja excluir:</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(teclado)
        )
        return SELECIONAR_REGULACAO_EXCLUIR

    except Exception as e:
        logger.error(f"Erro em iniciar_excluir: {e}")
        return ConversationHandler.END


async def selecionar_regulacao_excluir_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancelar_excl":
        await query.edit_message_text("❌ Operação de exclusão cancelada.")
        await query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)
        context.user_data.clear()
        return ConversationHandler.END

    context.user_data["excl_reg_id"] = query.data.replace("excl_reg_", "")
    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚠️ Sim, Excluir", callback_data="conf_excl_sim")],
        [InlineKeyboardButton("❌ Não, Cancelar", callback_data="cancelar_excl")]
    ])
    await query.edit_message_text(
        "<b>Tem certeza que deseja excluir esta regulação do monitoramento?</b>\nEsta ação não poderá ser desfeita.",
        parse_mode="HTML",
        reply_markup=teclado
    )
    return CONFIRMAR_EXCLUSAO


async def confirmar_exclusao_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "conf_excl_sim":
        reg_id = context.user_data.get("excl_reg_id")
        try:
            res = excluir_regulacao_db(reg_id)
            sucesso = await res if hasattr(res, "__await__") else res
        except Exception as e:
            logger.error(f"Erro ao excluir {reg_id}: {e}")
            sucesso = False

        if sucesso:
            await query.edit_message_text("✅ <b>Regulação excluída com sucesso do banco de dados!</b>", parse_mode="HTML")
        else:
            await query.edit_message_text("❌ Ocorreu um erro ao tentar excluir a regulação do banco de dados.")
    else:
        await query.edit_message_text("❌ Exclusão cancelada.")

    await query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)
    context.user_data.clear()
    return ConversationHandler.END


async def cancelar_excluir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("❌ Exclusão cancelada.")
        await update.callback_query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)
    else:
        await update.message.reply_text("❌ Exclusão cancelada.", reply_markup=TECLADO_MENU)
    return ConversationHandler.END