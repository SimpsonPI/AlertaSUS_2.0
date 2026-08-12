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

# Helper para formatar a data visualmente
def _formatar_data_br(data_str):
    if not data_str or str(data_str).upper() == "NONE":
        return "Não informado"
    data_str = str(data_str).strip()
    if "-" in data_str:
        partes = data_str.split("T")[0].split("-")
        if len(partes) == 3:
            return f"{partes[2]}/{partes[1]}/{partes[0]}"
    return data_str

# Helper para reformatar e exibir o formulário atualizado na tela
async def _exibir_formulario_edicao(update: Update, context: ContextTypes.DEFAULT_TYPE, editar_mensagem=True):
    num_reg = context.user_data.get("corr_num_reg")
    dados = context.user_data.get("corr_dados_temp", {})

    resumo = (
        f"📝 <b>Formulário de Edição - Regulação <code>{escape(str(num_reg))}</code></b>\n"
        f"<i>Modifique os campos desejados e clique em 'Salvar Alterações' no final.</i>\n\n"
        f"👤 <b>Nome:</b> {escape(str(dados.get('nome_paciente', '')))}\n"
        f"💳 <b>Cartão SUS:</b> {escape(str(dados.get('numero_sus', '')))}\n"
        f"📱 <b>Celular:</b> {escape(str(dados.get('celular', '')))}\n"
        f"🎂 <b>Nascimento:</b> {escape(_formatar_data_br(dados.get('data_nascimento', '')))}\n"
        f"🏷️ <b>CBO:</b> {escape(str(dados.get('cbo', '')))}\n"
        f"🩺 <b>Procedimento:</b> {escape(str(dados.get('procedimento', '')))}\n\n"
        f"<b>Escolha um campo para alterar:</b>"
    )

    teclado = [
        [InlineKeyboardButton("👤 Alterar Nome", callback_data="form_edit_nome_paciente")],
        [InlineKeyboardButton("💳 Alterar Cartão SUS", callback_data="form_edit_numero_sus")],
        [InlineKeyboardButton("📱 Alterar Celular", callback_data="form_edit_celular")],
        [InlineKeyboardButton("🎂 Alterar Nascimento", callback_data="form_edit_data_nascimento")],
        [InlineKeyboardButton("🏷️ Alterar CBO", callback_data="form_edit_cbo")],
        [InlineKeyboardButton("🩺 Alterar Procedimento", callback_data="form_edit_procedimento")],
        [InlineKeyboardButton("💾 SALVAR ALTERAÇÕES", callback_data="form_salvar_tudo")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_corr")]
    ]

    markup = InlineKeyboardMarkup(teclado)

    if editar_mensagem and update.callback_query:
        await update.callback_query.edit_message_text(resumo, parse_mode="HTML", reply_markup=markup)
    else:
        chat_id = update.effective_chat.id
        await context.bot.send_message(chat_id=chat_id, text=resumo, parse_mode="HTML", reply_markup=markup)

# ==================================================
# FLUXO DE CORREÇÃO DE REGULAÇÃO (FORMULÁRIO MULTI-EDIT)
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

        await update.message.reply_text(
            "✏️ <b>Selecione qual regulação deseja corrigir:</b>",
            reply_markup=InlineKeyboardMarkup(teclado),
            parse_mode="HTML"
        )
        return SELECIONAR_REGULACAO

    except Exception as e:
        logger.error(f"Erro em iniciar_corrigir: {e}")
        return ConversationHandler.END


async def selecionar_regulacao_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancelar_corr":
        await query.edit_message_text("❌ Operação de correção cancelada.")
        await query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)
        context.user_data.clear()
        return ConversationHandler.END

    num_reg = query.data.replace("corr_reg_", "").strip()
    context.user_data["corr_num_reg"] = num_reg

    # Carrega dados do banco para a memória local (rascunho)
    user_id = update.effective_user.id
    regulacoes = buscar_regulacoes_por_usuario(user_id)
    if hasattr(regulacoes, "__await__"):
        regulacoes = await regulacoes

    reg_atual = next((
        r for r in regulacoes 
        if str(r.get("numero_reg") or r.get("numero_regulacao") or r.get("id_regulacao") or r.get("id")) == str(num_reg)
    ), {})

    # Guarda o rascunho temporário
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
        await query.edit_message_text("❌ Operação de correção cancelada.")
        await query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)
        context.user_data.clear()
        return ConversationHandler.END

    # BOTÃO FINAL: SALVAR TUDO NO SUPABASE
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

        if erros == 0:
            await query.edit_message_text(f"✅ <b>Todas as alterações da regulação <code>{escape(str(num_reg))}</code> foram salvas com sucesso!</b>", parse_mode="HTML")
        else:
            await query.edit_message_text("⚠️ Algumas alterações podem não ter sido salvas. Verifique o banco de dados.")

        await query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)
        context.user_data.clear()
        return ConversationHandler.END

    # SELEÇÃO DE UM CAMPO PARA EDITAR
    campo_map = {
        "form_edit_nome_paciente": ("nome_paciente", "o **Nome do Paciente**"),
        "form_edit_numero_sus": ("numero_sus", "o **Cartão SUS**"),
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
        # Tratamento: maiúsculas automáticas para texto (preserva celular/data)
        if campo_em_edicao not in ["celular", "data_nascimento"]:
            novo_valor = novo_valor.upper()

        # Atualiza apenas no RASCUNHO temporário
        context.user_data["corr_dados_temp"][campo_em_edicao] = novo_valor

    # Reexibe o formulário com o campo atualizado para que o usuário possa alterar mais ou salvar
    await _exibir_formulario_edicao(update, context, editar_mensagem=False)
    return SELECIONAR_CAMPO


async def cancelar_corrigir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("❌ Operação de correção cancelada.")
        await update.callback_query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)
    else:
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