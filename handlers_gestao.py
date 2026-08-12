# handlers_gestao.py
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from database import (
    buscar_regulacoes_por_chat_id as buscar_regulacoes_por_usuario,
    atualizar_campo_regulacao,
    excluir_regulacao_db
)
from scraper import consultar_status_fms
from utils import (
    TECLADO_MENU, SELECIONAR_REGULACAO, SELECIONAR_CAMPO, AGUARDAR_NOVO_VALOR,
    SELECIONAR_REGULACAO_EXCLUIR, CONFIRMAR_EXCLUSAO, _extrair_id_e_nome, formatar_data,
    tratar_status_fms, _montar_msg_html, cancelar_operacao
)

try:
    from database import buscar_todas_regulacoes_ativas
except ImportError:
    try:
        from database import obter_todas_regulacoes as buscar_todas_regulacoes_ativas
    except ImportError:
        async def buscar_todas_regulacoes_ativas(): return []

logger = logging.getLogger(__name__)

# --- FLUXO CORRIGIR ---
async def iniciar_corrigir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    regulacoes = buscar_regulacoes_por_usuario(user_id)
    if hasattr(regulacoes, "__await__"): regulacoes = await regulacoes

    if not regulacoes:
        await update.message.reply_text("⚠️ Você não possui regulações cadastradas para corrigir.", reply_markup=TECLADO_MENU)
        return ConversationHandler.END

    teclado = []
    for r in regulacoes:
        db_id = r.get("id") or r.get("id_regulacao")
        num, nome = _extrair_id_e_nome(r)
        teclado.append([InlineKeyboardButton(f"📄 Reg: {num} - {nome}", callback_data=f"corr_reg_{db_id}")])

    teclado.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_corr")])
    await update.message.reply_text("✏️ <b>Selecione qual regulação deseja corrigir:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(teclado))
    return SELECIONAR_REGULACAO

async def selecionar_regulacao_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancelar_corr":
        await query.edit_message_text("❌ Operação de correção cancelada.")
        await query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)
        return ConversationHandler.END

    context.user_data["corr_reg_id"] = query.data.replace("corr_reg_", "")
    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("Cartão SUS", callback_data="corr_campo_numero_sus"), InlineKeyboardButton("Nome", callback_data="corr_campo_nome_paciente")],
        [InlineKeyboardButton("Celular", callback_data="corr_campo_celular"), InlineKeyboardButton("Nascimento", callback_data="corr_campo_data_nascimento")],
        [InlineKeyboardButton("Nº Regulação", callback_data="corr_campo_numero_reg"), InlineKeyboardButton("CBO", callback_data="corr_campo_cbo")],
        [InlineKeyboardButton("Procedimento", callback_data="corr_campo_procedimento"), InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_corr")]
    ])
    await query.edit_message_text("Selecione qual campo você deseja alterar:", reply_markup=teclado)
    return SELECIONAR_CAMPO

async def selecionar_campo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancelar_corr":
        await query.edit_message_text("❌ Operação de correção cancelada.")
        await query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)
        context.user_data.clear()
        return ConversationHandler.END

    campo = query.data.replace("corr_campo_", "").strip()
    context.user_data["corr_campo"] = campo

    rotulos = {
        "data_nascimento": "Data de Nascimento", "celular": "Celular",
        "nome_paciente": "Nome do Paciente", "numero_sus": "Número do Cartão SUS", "cbo": "CBO / Especialidade"
    }
    nome_exibicao = rotulos.get(campo, campo.replace("_", " ").title())
    await query.edit_message_text(f"✏️ Digite o novo valor para <b>{nome_exibicao}</b>:", parse_mode="HTML")
    return AGUARDAR_NOVO_VALOR

async def salvar_novo_valor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    novo_valor = update.message.text.strip()
    reg_id = context.user_data.get("corr_reg_id") or context.user_data.get("reg_id")
    campo = context.user_data.get("corr_campo")

    if not reg_id or not campo:
        await update.message.reply_text("⚠️ <b>Dados da sessão perdidos.</b> Por favor, inicie a correção novamente.", parse_mode="HTML", reply_markup=TECLADO_MENU)
        context.user_data.clear()
        return ConversationHandler.END

    if campo == "data_nascimento": novo_valor = formatar_data(novo_valor)

    try:
        res = atualizar_campo_regulacao(reg_id, campo, novo_valor)
        sucesso = await res if hasattr(res, "__await__") else res
    except Exception as e:
        logger.error(f"Erro ao atualizar campo {campo}: {e}")
        sucesso = False

    if sucesso:
        await update.message.reply_text("✅ <b>Registro atualizado com sucesso no banco de dados!</b>", parse_mode="HTML", reply_markup=TECLADO_MENU)
    else:
        await update.message.reply_text("❌ Falha ao atualizar o registro no banco de dados. Tente novamente mais tarde.", reply_markup=TECLADO_MENU)

    context.user_data.clear()
    return ConversationHandler.END

# --- FLUXO EXCLUIR ---
async def iniciar_excluir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    regulacoes = buscar_regulacoes_por_usuario(user_id)
    if hasattr(regulacoes, "__await__"): regulacoes = await regulacoes

    if not regulacoes:
        await update.message.reply_text("⚠️ Você não possui nenhuma regulação cadastrada para excluir.", reply_markup=TECLADO_MENU)
        return ConversationHandler.END

    teclado = []
    for r in regulacoes:
        db_id = r.get("id") or r.get("id_regulacao")
        num, nome = _extrair_id_e_nome(r)
        teclado.append([InlineKeyboardButton(f"🗑️ Reg: {num} - {nome}", callback_data=f"excl_reg_{db_id}")])

    teclado.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_excl")])
    await update.message.reply_text("🗑️ <b>Selecione qual regulação deseja excluir:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(teclado))
    return SELECIONAR_REGULACAO_EXCLUIR

async def selecionar_regulacao_excluir_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancelar_excl":
        await query.edit_message_text("❌ Operação de exclusão cancelada.")
        await query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)
        return ConversationHandler.END

    context.user_data["excl_reg_id"] = query.data.replace("excl_reg_", "")
    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚠️ Sim, Excluir", callback_data="conf_excl_sim")],
        [InlineKeyboardButton("❌ Não, Cancelar", callback_data="cancelar_excl")]
    ])
    await query.edit_message_text("<b>Tem certeza que deseja excluir esta regulação do monitoramento?</b>\nEsta ação não poderá ser desfeita.", parse_mode="HTML", reply_markup=teclado)
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

# --- VARREDURA AUTOMÁTICA ---
async def executar_varredura_automatica(context: ContextTypes.DEFAULT_TYPE):
    logger.info("🤖 Iniciando varredura automática de regulações...")
    regulacoes = await buscar_todas_regulacoes_ativas()

    for reg in regulacoes:
        num_reg, _ = _extrair_id_e_nome(reg)
        telegram_id = reg.get("id_do_chat") or reg.get("telegram_id")
        status_antigo = reg.get("status_anterior") or reg.get("status_atual")

        resultado = await consultar_status_fms(num_reg)

        if resultado.get("sucesso"):
            novo_status = tratar_status_fms(resultado.get("status"))
            if novo_status and novo_status != status_antigo:
                reg_db_id = reg.get("id") or reg.get("id_regulacao")
                if reg_db_id:
                    res = atualizar_campo_regulacao(reg_db_id, "status_anterior", novo_status)
                    if hasattr(res, "__await__"): await res
                
                msg_notificacao = f"🔔 <b>MUDANÇA DE STATUS DETECTADA!</b>\n\n{_montar_msg_html(num_reg, resultado, reg)}"
                try:
                    await context.bot.send_message(chat_id=telegram_id, text=msg_notificacao, parse_mode="HTML")
                except Exception as e:
                    logger.error(f"Erro ao notificar {telegram_id}: {e}")