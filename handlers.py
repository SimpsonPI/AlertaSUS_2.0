import re
import asyncio
import logging
import traceback
from html import escape

from telegram import Update, BotCommand, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
)
from config import supabase
from scraper import consultar_status_fms, formatar_data_br, nome_paciente_exibicao

# Estados dos Fluxos Interativos
(
    CONSULTAR_ID,
    CORRIGIR_ANTIGO,
    CORRIGIR_NOVO,
    EXCLUIR_ID,
    EXCLUIR_CONFIRM,
) = range(5)

# Links do Formulário de Cadastro
URL_FORMULARIO_PAGES = "https://simpsonpi.github.io/alerta-sus-bot/"
URL_GITHUB_REPO = "https://github.com/SimpsonPI/alerta-sus-bot"

# Teclado Principal
TECLADO_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📋 Verificar Todas"), KeyboardButton("🔍 Verificar Específico")],
        [KeyboardButton("➕ Cadastrar Nova"), KeyboardButton("✏️ Corrigir ID")],
        [KeyboardButton("❌ Excluir Regulação"), KeyboardButton("ℹ️ Ajuda")]
    ],
    resize_keyboard=True
)

# Teclado de Confirmação de Exclusão
TECLADO_CONFIRMACAO = ReplyKeyboardMarkup(
    [
        [KeyboardButton("✅ Sim, confirmar exclusão")],
        [KeyboardButton("❌ Não, cancelar")]
    ],
    resize_keyboard=True,
    one_time_keyboard=True
)

def _montar_msg_html(numero_reg: str, resultado: dict, reg_db: dict | None = None) -> str:
    """Gera mensagem de status formatada em HTML seguro."""
    reg_db = reg_db or {}
    nome = escape(nome_paciente_exibicao(reg_db.get("nome_paciente")))
    dt_nasc = escape(formatar_data_br(reg_db.get("data_nascimento")))
    email = escape(reg_db.get("email") or reg_db.get("e-mail") or "Não informado")
    celular = escape(reg_db.get("celular") or "Não informado")
    num_esc = escape(str(numero_reg))

    status = escape(str(resultado.get("status_resumido") or resultado.get("situacao") or "Informada no portal"))
    posicao = escape(str(resultado.get("posicao_fila") or "Não informada"))
    previsao = escape(str(resultado.get("previsao_atendimento") or "Não informada"))

    return (
        f"🏥 <b>SITUAÇÃO DA REGULAÇÃO</b>\n\n"
        f"👤 <b>Paciente:</b> {nome}\n"
        f"🎂 <b>Data de Nascimento:</b> {dt_nasc}\n"
        f"📧 <b>E-mail:</b> {email}\n"
        f"📱 <b>Celular:</b> {celular}\n"
        f"🆔 <b>ID de Regulação:</b> <code>{num_esc}</code>\n\n"
        f"📌 <b>Situação:</b> {status}\n"
        f"• <b>Posição da Fila:</b> {posicao}\n"
        f"• <b>Previsão de atendimento:</b> {previsao}"
    )

# --- COMANDOS BÁSICOS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    nome_usuario = escape(update.effective_user.first_name or "Cidadão")
    mensagem = (
        f"👋 Olá, <b>{nome_usuario}</b>! Bem-vindo ao <b>AlertaSUS 2.0</b>!\n\n"
        "Escolha uma opção no menu abaixo para começar:"
    )
    await update.message.reply_text(mensagem, reply_markup=TECLADO_MENU, parse_mode="HTML")
    return ConversationHandler.END

async def comando_ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    texto_ajuda = (
        "ℹ️ <b>Central de Ajuda - AlertaSUS 2.0</b>\n\n"
        f"• <b>➕ Cadastrar Nova:</b> Acesse o formulário de cadastro web (<a href='{URL_FORMULARIO_PAGES}'>Abrir Formulário</a>).\n"
        "• <b>📋 Verificar Todas:</b> Consulta o status de todos os seus IDs cadastrados.\n"
        "• <b>🔍 Verificar Específico:</b> Consulta um único ID informado na hora.\n"
        "• <b>✏️ Corrigir ID:</b> Altera um ID antigo para um novo ID.\n"
        "• <b>❌ Excluir Regulação:</b> Remove um ID mediante confirmação.\n\n"
        "⏰ <b>Varreduras automáticas:</b> Diariamente às 08:00 e 18:00."
    )
    await update.message.reply_text(texto_ajuda, reply_markup=TECLADO_MENU, parse_mode="HTML", disable_web_page_preview=True)
    return ConversationHandler.END

async def cancelar_operacao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Operação cancelada.", reply_markup=TECLADO_MENU)
    context.user_data.clear()
    return ConversationHandler.END

# --- 1. CADASTRAR NOVA (LINK WEB) ---

async def abrir_link_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    mensagem = (
        "📝 <b>Cadastro de Nova Regulação</b>\n\n"
        "Para realizar o cadastro, acesse o formulário pelo link abaixo:\n\n"
        f"🔗 <a href='{URL_FORMULARIO_PAGES}'><b>Clique aqui para abrir o Formulário de Cadastro</b></a>\n\n"
        f"📌 <i>Repositório do projeto:</i> {URL_GITHUB_REPO}"
    )
    await update.message.reply_text(
        mensagem,
        reply_markup=TECLADO_MENU,
        parse_mode="HTML",
        disable_web_page_preview=False
    )
    return ConversationHandler.END

# --- 2. VERIFICAR TODAS ---

async def comando_verificar_todas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    msg_espera = await update.message.reply_text("🔍 <b>Consultando todas as suas regulações no sistema...</b>", parse_mode="HTML")

    try:
        resposta = await asyncio.to_thread(
            lambda: supabase.table("AlertaSUS_2.0").select("*").eq("id_do_chat", chat_id).execute()
        )
        regulacoes = resposta.data or []

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
                await update.message.reply_text(
                    f"⚠️ Falha ao consultar a regulação <code>{escape(numero_reg)}</code>.",
                    parse_mode="HTML"
                )

    except Exception as e:
        logging.error(f"Erro ao consultar regulações: {traceback.format_exc()}")
        await msg_espera.edit_text("❌ Ocorreu um erro ao acessar o banco de dados. Tente novamente em instantes.")

    return ConversationHandler.END

# --- 3. VERIFICAR ESPECÍFICO ---

async def iniciar_verificar_especifico(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "🔍 Digite o <b>Número da Regulação (ID)</b> que deseja consultar agora:\n\n"
        "<i>(Ou digite /cancelar para sair)</i>",
        parse_mode="HTML"
    )
    return CONSULTAR_ID

async def processar_verificar_especifico(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    numero_reg = re.sub(r"\D", "", update.message.text)
    chat_id = update.effective_chat.id

    if not numero_reg:
        await update.message.reply_text("⚠️ Por favor, digite apenas os números do ID da regulação:")
        return CONSULTAR_ID

    msg_espera = await update.message.reply_text(f"🔎 Pesquisando ID <code>{escape(numero_reg)}</code> na FMS...", parse_mode="HTML")

    reg_db = None
    try:
        resposta = await asyncio.to_thread(
            lambda: supabase.table("AlertaSUS_2.0")
            .select("*")
            .eq("id_do_chat", chat_id)
            .eq("numero_reg", numero_reg)
            .execute()
        )
        if resposta.data:
            reg_db = resposta.data[0]
    except Exception as err:
        logging.warning(f"Aviso de busca no DB: {err}")

    resultado = await consultar_status_fms(numero_reg)
    await msg_espera.delete()

    if resultado.get("sucesso"):
        msg_html = _montar_msg_html(numero_reg, resultado, reg_db)
        await update.message.reply_text(msg_html, parse_mode="HTML", reply_markup=TECLADO_MENU)
    else:
        msg_erro = resultado.get("mensagem") or "Regulação não encontrada na FMS."
        await update.message.reply_text(f"❌ {escape(msg_erro)}", parse_mode="HTML", reply_markup=TECLADO_MENU)

    return ConversationHandler.END

# --- 4. CORRIGIR ID ---

async def iniciar_corrigir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "✏️ <b>Passo 1 de 2:</b> Digite o <b>ID da Regulação ANTIGO</b> que você quer alterar:\n\n"
        "<i>(Ou digite /cancelar para sair)</i>",
        parse_mode="HTML"
    )
    return CORRIGIR_ANTIGO

async def processar_corrigir_antigo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    id_antigo = re.sub(r"\D", "", update.message.text)
    if not id_antigo:
        await update.message.reply_text("⚠️ Digite um ID numérico válido:")
        return CORRIGIR_ANTIGO

    context.user_data["id_antigo"] = id_antigo
    await update.message.reply_text(
        f"✏️ <b>Passo 2 de 2:</b> Digite o <b>NOVO ID</b> para substituir o ID <code>{escape(id_antigo)}</code>:",
        parse_mode="HTML"
    )
    return CORRIGIR_NOVO

async def processar_corrigir_novo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    id_novo = re.sub(r"\D", "", update.message.text)
    chat_id = update.effective_chat.id
    id_antigo = context.user_data.get("id_antigo")

    if not id_novo:
        await update.message.reply_text("⚠️ Digite um ID numérico válido para o novo código:")
        return CORRIGIR_NOVO

    try:
        resultado_fms = await consultar_status_fms(id_novo)
        novo_status = resultado_fms.get("status_resumido", "Pendente") if resultado_fms.get("sucesso") else "Atualizado"

        resp = await asyncio.to_thread(
            lambda: supabase.table("AlertaSUS_2.0").update({
                "numero_reg": id_novo,
                "status_anterior": novo_status
            }).eq("id_do_chat", chat_id).eq("numero_reg", id_antigo).execute()
        )

        if resp.data:
            await update.message.reply_text(
                f"✅ Regulação <code>{escape(id_antigo)}</code> alterada com sucesso para <code>{escape(id_novo)}</code>!",
                reply_markup=TECLADO_MENU,
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text(
                f"⚠️ A regulação <code>{escape(id_antigo)}</code> não foi encontrada no seu cadastro.",
                reply_markup=TECLADO_MENU,
                parse_mode="HTML"
            )
    except Exception as e:
        logging.error(f"Erro ao corrigir ID: {e}")
        await update.message.reply_text("❌ Erro ao atualizar no banco de dados.", reply_markup=TECLADO_MENU)

    context.user_data.clear()
    return ConversationHandler.END

# --- 5. EXCLUIR REGULAÇÃO (COM CONFIRMAÇÃO) ---

async def iniciar_excluir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    resposta = await asyncio.to_thread(
        lambda: supabase.table("AlertaSUS_2.0").select("numero_reg, nome_paciente").eq("id_do_chat", chat_id).execute()
    )
    regs = resposta.data or []

    if not regs:
        await update.message.reply_text("ℹ️ Você não possui nenhuma regulação cadastrada para excluir.", reply_markup=TECLADO_MENU)
        return ConversationHandler.END

    lista_txt = "\n".join([f"• <code>{r.get('numero_reg')}</code> - {escape(r.get('nome_paciente') or 'Sem nome')}" for r in regs])
    await update.message.reply_text(
        f"❌ <b>Exclusão de Regulação</b>\n\n"
        f"Suas regulações salvas:\n{lista_txt}\n\n"
        f"Digite o <b>Número da Regulação (ID)</b> que deseja excluir:\n"
        f"<i>(Ou digite /cancelar para sair)</i>",
        parse_mode="HTML"
    )
    return EXCLUIR_ID

async def processar_excluir_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    id_excluir = re.sub(r"\D", "", update.message.text)

    if not id_excluir:
        await update.message.reply_text("⚠️ Informe um ID de regulação numérico válido:")
        return EXCLUIR_ID

    context.user_data["id_excluir"] = id_excluir
    await update.message.reply_text(
        f"⚠️ <b>CONFIRMAÇÃO DE EXCLUSÃO</b>\n\n"
        f"Tem certeza de que deseja excluir permanentemente o ID <code>{escape(id_excluir)}</code>?",
        reply_markup=TECLADO_CONFIRMACAO,
        parse_mode="HTML"
    )
    return EXCLUIR_CONFIRM

async def processar_excluir_confirmacao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    resposta_texto = update.message.text.strip()
    chat_id = update.effective_chat.id
    id_excluir = context.user_data.get("id_excluir")

    if "Sim" in resposta_texto:
        try:
            res = await asyncio.to_thread(
                lambda: supabase.table("AlertaSUS_2.0").delete().eq("id_do_chat", chat_id).eq("numero_reg", id_excluir).execute()
            )
            if res.data:
                await update.message.reply_text(
                    f"✅ Regulação <code>{escape(id_excluir)}</code> excluída com sucesso!",
                    reply_markup=TECLADO_MENU,
                    parse_mode="HTML"
                )
            else:
                await update.message.reply_text(
                    f"⚠️ O ID <code>{escape(id_excluir)}</code> não foi localizado para exclusão.",
                    reply_markup=TECLADO_MENU,
                    parse_mode="HTML"
                )
        except Exception as error:
            logging.error(f"Erro ao excluir: {error}")
            await update.message.reply_text("⚠️ Falha ao remover a regulação do banco de dados.", reply_markup=TECLADO_MENU)
    else:
        await update.message.reply_text("❌ Exclusão cancelada.", reply_markup=TECLADO_MENU)

    context.user_data.clear()
    return ConversationHandler.END

async def configurar_menu_comandos(application):
    comandos = [
        BotCommand("start", "Iniciar bot e exibir menu principal"),
        BotCommand("cadastrar", "Link do formulário de cadastro"),
        BotCommand("verificar", "Verificar todas as regulações"),
        BotCommand("consultar", "Verificar regulação específica"),
        BotCommand("corrigir", "Corrigir ID de regulação"),
        BotCommand("excluir", "Excluir regulação com confirmação"),
        BotCommand("ajuda", "Central de ajuda")
    ]
    await application.bot.set_my_commands(comandos)