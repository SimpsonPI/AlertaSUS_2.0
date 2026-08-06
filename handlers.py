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
from database import executar_cadastro_regulacao

# Estados das Conversas Interativas
(
    CAD_REGULACAO,
    CAD_NOME,
    CAD_DATA_NASC,
    CAD_EMAIL,
    CAD_CELULAR,
    CONSULTAR_ID,
    EXCLUIR_ID,
    CORRIGIR_ANTIGO,
    CORRIGIR_NOVO,
) = range(9)

# Teclado Principal Atualizado
TECLADO_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📋 Consultar Todos"), KeyboardButton("🔍 Consultar Específico")],
        [KeyboardButton("➕ Cadastrar Nova"), KeyboardButton("✏️ Corrigir ID")],
        [KeyboardButton("❌ Excluir Regulação"), KeyboardButton("ℹ️ Ajuda / Manual")]
    ],
    resize_keyboard=True
)

def _montar_msg_html(numero_reg: str, resultado: dict, reg_db: dict | None = None) -> str:
    """Gera mensagem formatada em HTML seguro."""
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
        "• <b>📋 Consultar Todos:</b> Exibe o status de todas as suas regulações registradas.\n"
        "• <b>🔍 Consultar Específico:</b> Consulta qualquer ID de regulação na hora.\n"
        "• <b>➕ Cadastrar Nova:</b> Formulário interativo para registrar um novo acompanhamento.\n"
        "• <b>✏️ Corrigir ID:</b> Altera um ID de regulação existente.\n"
        "• <b>❌ Excluir Regulação:</b> Remove uma regulação da sua lista de monitoramento.\n\n"
        "⏰ <b>Varreduras automáticas:</b> Diariamente às 08:00 e 18:00."
    )
    await update.message.reply_text(texto_ajuda, reply_markup=TECLADO_MENU, parse_mode="HTML")
    return ConversationHandler.END

async def cancelar_operacao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Operação cancelada.", reply_markup=TECLADO_MENU)
    context.user_data.clear()
    return ConversationHandler.END

# --- CONSULTA GERAL ---

async def comando_verificar_agora(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    msg_espera = await update.message.reply_text("🔍 <b>Consultando suas regulações no sistema...</b>", parse_mode="HTML")

    try:
        resposta = await asyncio.to_thread(
            lambda: supabase.table("AlertaSUS_2.0").select("*").eq("id_do_chat", chat_id).execute()
        )
        regulacoes = resposta.data or []

        if not regulacoes:
            await msg_espera.edit_text(
                "ℹ️ Nenhuma regulação cadastrada para a sua conta.\nUtilize <b>➕ Cadastrar Nova</b> para registrar.",
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
                    f"⚠️ Falha temporária ao consultar a regulação <code>{escape(numero_reg)}</code>.",
                    parse_mode="HTML"
                )

    except Exception as e:
        logging.error(f"Erro no comando verificar:\n{traceback.format_exc()}")
        await msg_espera.edit_text("❌ Ocorreu um erro ao acessar o banco de dados. Tente novamente em instantes.")

    return ConversationHandler.END

# --- CONSULTA ESPECÍFICA (INTERATIVA) ---

async def iniciar_consulta_especifica(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "🔍 Digite o <b>Número da Regulação (ID)</b> que deseja consultar agora:\n\n"
        "<i>(Ou digite /cancelar para fechar)</i>",
        parse_mode="HTML"
    )
    return CONSULTAR_ID

async def processar_consulta_especifica(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    numero_reg = re.sub(r"\D", "", update.message.text)
    chat_id = update.effective_chat.id

    if not numero_reg:
        await update.message.reply_text("⚠️ Por favor, informe apenas os números do ID da regulação.")
        return CONSULTAR_ID

    msg_espera = await update.message.reply_text(f"🔎 Pesquisando regulação <code>{escape(numero_reg)}</code> na FMS...", parse_mode="HTML")

    # Verifica se já existe no Supabase para pegar os dados do paciente
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
        logging.warning(f"Erro ao buscar no DB: {err}")

    resultado = await consultar_status_fms(numero_reg)
    await msg_espera.delete()

    if resultado.get("sucesso"):
        msg_html = _montar_msg_html(numero_reg, resultado, reg_db)
        await update.message.reply_text(msg_html, parse_mode="HTML", reply_markup=TECLADO_MENU)
    else:
        msg_erro = resultado.get("mensagem") or "Regulação não encontrada na FMS."
        await update.message.reply_text(f"❌ {escape(msg_erro)}", parse_mode="HTML", reply_markup=TECLADO_MENU)

    return ConversationHandler.END

# --- FORMULÁRIO INTERATIVO DE CADASTRO ---

async def iniciar_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "📝 <b>Passo 1 de 5: Número da Regulação</b>\n\n"
        "Digite apenas o <b>Número da Regulação (ID)</b> que deseja monitorar:\n"
        "📌 <i>Exemplo: 10829301</i>",
        parse_mode="HTML"
    )
    return CAD_REGULACAO

async def cad_passo_regulacao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    numero_reg = re.sub(r"\D", "", update.message.text)
    if not numero_reg:
        await update.message.reply_text("⚠️ Número inválido. Digite apenas os dígitos numéricos da regulação:")
        return CAD_REGULACAO

    context.user_data["numero_reg"] = numero_reg
    await update.message.reply_text(
        "👤 <b>Passo 2 de 5: Nome do Paciente</b>\n\n"
        "Digite o <b>Nome Completo</b> do paciente:",
        parse_mode="HTML"
    )
    return CAD_NOME

async def cad_passo_nome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    nome = update.message.text.strip()
    if len(nome) < 3:
        await update.message.reply_text("⚠️ Por favor, informe o nome completo do paciente:")
        return CAD_NOME

    context.user_data["nome_paciente"] = nome
    await update.message.reply_text(
        "🎂 <b>Passo 3 de 5: Data de Nascimento</b>\n\n"
        "Digite a data de nascimento no formato <b>DD/MM/AAAA</b>:\n"
        "📌 <i>Exemplo: 27/03/1978</i>",
        parse_mode="HTML"
    )
    return CAD_DATA_NASC

async def cad_passo_data_nasc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    data_str = update.message.text.strip()
    context.user_data["data_nascimento"] = data_str
    await update.message.reply_text(
        "📧 <b>Passo 4 de 5: E-mail</b>\n\n"
        "Digite o <b>E-mail</b> de contato do paciente (ou digite <code>pular</code>):",
        parse_mode="HTML"
    )
    return CAD_EMAIL

async def cad_passo_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    email_str = update.message.text.strip()
    context.user_data["email"] = email_str
    await update.message.reply_text(
        "📱 <b>Passo 5 de 5: Celular / WhatsApp</b>\n\n"
        "Digite o número do <b>Celular com DDD</b> (ou digite <code>pular</code>):\n"
        "📌 <i>Exemplo: 86998271235</i>",
        parse_mode="HTML"
    )
    return CAD_CELULAR

async def cad_passo_finalizar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    celular_str = update.message.text.strip()
    chat_id = update.effective_chat.id

    numero_reg = context.user_data.get("numero_reg")
    nome_paciente = context.user_data.get("nome_paciente")
    data_nascimento = context.user_data.get("data_nascimento")
    email = context.user_data.get("email")

    msg_aguarde = await update.message.reply_text("💾 <b>Verificando na FMS e salvando cadastro...</b>", parse_mode="HTML")

    sucesso, mensagem = await executar_cadastro_regulacao(
        chat_id=chat_id,
        numero_reg=numero_reg,
        nome_paciente=nome_paciente,
        data_nascimento=data_nascimento,
        email=email,
        celular=celular_str
    )

    await msg_aguarde.delete()

    if not sucesso:
        await update.message.reply_text(
            f"❌ <b>Não foi possível cadastrar:</b> {escape(mensagem)}",
            reply_markup=TECLADO_MENU,
            parse_mode="HTML"
        )

    context.user_data.clear()
    return ConversationHandler.END

# --- EXCLUSÃO INTERATIVA ---

async def iniciar_exclusao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
        f"Digite o <b>Número da Regulação (ID)</b> que você deseja excluir:\n"
        f"<i>(Ou digite /cancelar para desistir)</i>",
        parse_mode="HTML"
    )
    return EXCLUIR_ID

async def processar_exclusao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    numero_reg = re.sub(r"\D", "", update.message.text)
    chat_id = update.effective_chat.id

    if not numero_reg:
        await update.message.reply_text("⚠️ Informe um ID de regulação válido:")
        return EXCLUIR_ID

    try:
        supabase.table("AlertaSUS_2.0").delete().eq("id_do_chat", chat_id).eq("numero_reg", numero_reg).execute()
        await update.message.reply_text(
            f"✅ Regulação <code>{escape(numero_reg)}</code> excluída com sucesso!",
            reply_markup=TECLADO_MENU,
            parse_mode="HTML"
        )
    except Exception as error:
        logging.error(f"Erro ao excluir: {error}")
        await update.message.reply_text("⚠️ Falha ao remover a regulação do banco de dados.", reply_markup=TECLADO_MENU)

    return ConversationHandler.END

# --- CORREÇÃO DE ID INTERATIVA ---

async def iniciar_correcao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "✏️ <b>Passo 1 de 2: ID Antigo</b>\n\n"
        "Digite o <b>ID da Regulação ANTIGO</b> que você quer alterar:\n"
        "<i>(Ou digite /cancelar para desistir)</i>",
        parse_mode="HTML"
    )
    return CORRIGIR_ANTIGO

async def correcao_passo_antigo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    id_antigo = re.sub(r"\D", "", update.message.text)
    if not id_antigo:
        await update.message.reply_text("⚠️ Digite um ID numérico válido:")
        return CORRIGIR_ANTIGO

    context.user_data["id_antigo"] = id_antigo
    await update.message.reply_text(
        "✏️ <b>Passo 2 de 2: ID Novo</b>\n\n"
        "Agora digite o <b>NOVO ID correto</b> da regulação:",
        parse_mode="HTML"
    )
    return CORRIGIR_NOVO

async def correcao_passo_novo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    id_novo = re.sub(r"\D", "", update.message.text)
    chat_id = update.effective_chat.id
    id_antigo = context.user_data.get("id_antigo")

    if not id_novo:
        await update.message.reply_text("⚠️ Digite um ID numérico válido para o novo código:")
        return CORRIGIR_NOVO

    try:
        resultado_fms = await consultar_status_fms(id_novo)
        novo_status = resultado_fms.get("status_resumido", "Pendente") if resultado_fms.get("sucesso") else "Atualizado"

        resp = supabase.table("AlertaSUS_2.0").update({
            "numero_reg": id_novo,
            "status_anterior": novo_status
        }).eq("id_do_chat", chat_id).eq("numero_reg", id_antigo).execute()

        if resp.data:
            await update.message.reply_text(
                f"✅ Regulação <code>{escape(id_antigo)}</code> alterada com sucesso para <code>{escape(id_novo)}</code>!",
                reply_markup=TECLADO_MENU,
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text(
                f"⚠️ A regulação <code>{escape(id_antigo)}</code> não foi encontrada na sua conta.",
                reply_markup=TECLADO_MENU,
                parse_mode="HTML"
            )
    except Exception as e:
        logging.error(f"Erro ao corrigir ID: {e}")
        await update.message.reply_text("❌ Erro ao atualizar no banco de dados.", reply_markup=TECLADO_MENU)

    context.user_data.clear()
    return ConversationHandler.END

async def configurar_menu_comandos(application):
    comandos = [
        BotCommand("start", "Iniciar bot e exibir menu principal"),
        BotCommand("verificar", "Consultar todas as regulações"),
        BotCommand("consultar", "Consultar uma regulação específica"),
        BotCommand("cadastrar", "Cadastrar nova regulação"),
        BotCommand("corrigir", "Corrigir ID de regulação"),
        BotCommand("excluir", "Excluir regulação"),
        BotCommand("ajuda", "Central de ajuda")
    ]
    await application.bot.set_my_commands(comandos)