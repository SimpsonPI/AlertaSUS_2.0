import re
import asyncio
import logging
import traceback
from html import escape

from telegram import Update, BotCommand, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes
from config import supabase
from scraper import consultar_status_fms, formatar_data_br, nome_paciente_exibicao

TECLADO_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📋 Consultar Todos"), KeyboardButton("➕ Cadastrar Nova")],
        [KeyboardButton("✏️ Corrigir ID"), KeyboardButton("❌ Excluir Regulação")],
        [KeyboardButton("ℹ️ Ajuda / Manual")]
    ],
    resize_keyboard=True
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    nome_usuario = escape(update.effective_user.first_name or "Cidadão")
    mensagem = (
        f"👋 Olá, <b>{nome_usuario}</b>! Bem-vindo ao <b>AlertaSUS 2.0</b>!\n\n"
        "Escolha uma opção no menu abaixo para começar:"
    )
    await update.message.reply_text(mensagem, reply_markup=TECLADO_MENU, parse_mode="HTML")

async def comando_ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    texto_ajuda = (
        "ℹ️ <b>Central de Ajuda - AlertaSUS 2.0</b>\n\n"
        "• Clique em <b>📋 Consultar Todos</b> para verificar suas regulações.\n"
        "• Clique em <b>➕ Cadastrar Nova</b> para incluir um novo ID de regulação.\n"
        "• Clique em <b>❌ Excluir Regulação</b> para remover um acompanhamento.\n\n"
        "⏰ <b>Varreduras automáticas:</b> Diariamente às 08:00 e 18:00."
    )
    await update.message.reply_text(texto_ajuda, reply_markup=TECLADO_MENU, parse_mode="HTML")

async def comando_cadastrar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["aguardando_regula"] = True
    mensagem = (
        "📝 <b>Cadastro no AlertaSUS 2.0</b>\n\n"
        "Por favor, digite apenas o <b>Número da Regulação (ID)</b> que deseja monitorar.\n\n"
        "📌 <b>Exemplo:</b> <code>10829301</code>"
    )
    await update.message.reply_text(mensagem, reply_markup=TECLADO_MENU, parse_mode="HTML")

def _montar_msg_html(numero_reg: str, resultado: dict, reg_db: dict) -> str:
    """Gera mensagem formatada em HTML seguro."""
    nome = escape(nome_paciente_exibicao(reg_db.get("nome_paciente")))
    dt_nasc = escape(formatar_data_br(reg_db.get("data_nascimento")))
    email = escape(reg_db.get("email") or "Não informado")
    num_esc = escape(str(numero_reg))

    status = escape(str(resultado.get("status_resumido") or resultado.get("situacao") or "Informada no portal"))
    posicao = escape(str(resultado.get("posicao_fila") or "Não informada"))
    previsao = escape(str(resultado.get("previsao_atendimento") or "Não informada"))

    return (
        f"🏥 <b>SITUAÇÃO DA REGULAÇÃO</b>\n\n"
        f"👤 <b>Paciente:</b> {nome}\n"
        f"🎂 <b>Data de Nascimento:</b> {dt_nasc}\n"
        f"📧 <b>E-mail:</b> {email}\n"
        f"🆔 <b>ID de Regulação:</b> <code>{num_esc}</code>\n\n"
        f"📌 <b>Situação:</b> {status}\n"
        f"• <b>Posição da Fila:</b> {posicao}\n"
        f"• <b>Previsão de atendimento:</b> {previsao}"
    )

async def comando_verificar_agora(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    msg_espera = await update.message.reply_text("🔍 <b>Consultando regulações no sistema...</b>", parse_mode="HTML")

    try:
        # Busca no Supabase (convertendo chat_id para str ou int conforme armazenado)
        resposta = await asyncio.to_thread(
            lambda: supabase.table("AlertaSUS_2.0").select("*").eq("id_do_chat", chat_id).execute()
        )
        regulacoes = resposta.data or []

        if not regulacoes:
            await msg_espera.edit_text(
                "ℹ️ Nenhuma regulação cadastrada para a sua conta.\nUtilize <b>➕ Cadastrar Nova</b> para registrar.",
                parse_mode="HTML"
            )
            return

        for reg in regulacoes:
            numero_reg = reg.get("numero_reg")
            if not numero_reg:
                continue

            resultado = await consultar_status_fms(numero_reg)

            if resultado.get("sucesso"):
                msg_html = _montar_msg_html(numero_reg, resultado, reg)
                await update.message.reply_text(msg_html, parse_mode="HTML")
            else:
                msg_erro = resultado.get("mensagem") or "Não foi possível consultar esta regulação."
                await update.message.reply_text(
                    f"❌ <b>ID {escape(str(numero_reg))}:</b> {escape(msg_erro)}",
                    parse_mode="HTML"
                )

        await msg_espera.delete()

    except Exception as e:
        logging.error(f"Erro detalhado no comando verificar:\n{traceback.format_exc()}")
        await msg_espera.edit_text("❌ Ocorreu um erro ao consultar suas regulações. Verifique os logs do servidor.")

async def comando_excluir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("⚠️ Informe o número da regulação. Exemplo: <code>/excluir 12345678</code>", parse_mode="HTML")
        return

    numero_reg = re.sub(r"\D", "", context.args[0])
    try:
        supabase.table("AlertaSUS_2.0").delete().eq("id_do_chat", chat_id).eq("numero_reg", numero_reg).execute()
        await update.message.reply_text(f"✅ Regulação <code>{escape(numero_reg)}</code> excluída com sucesso!", parse_mode="HTML")
    except Exception as error:
        logging.error(f"Erro ao excluir: {error}")
        await update.message.reply_text("⚠️ Falha ao remover a regulação.")

async def comando_corrigir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "✏️ Digite <code>/corrigir ID_ANTIGO ID_NOVO</code> para alterar um registro.\nExemplo: <code>/corrigir 12345678 87654321</code>",
        parse_mode="HTML"
    )

async def processar_texto_usuario(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    texto = update.message.text.strip()
    chat_id = update.effective_chat.id

    if texto == "📋 Consultar Todos":
        await comando_verificar_agora(update, context)
        return
    elif texto == "➕ Cadastrar Nova":
        await comando_cadastrar(update, context)
        return
    elif texto == "✏️ Corrigir ID":
        await comando_corrigir(update, context)
        return
    elif texto == "❌ Excluir Regulação":
        await comando_excluir(update, context)
        return
    elif texto == "ℹ️ Ajuda / Manual":
        await comando_ajuda(update, context)
        return

    if context.user_data.get("aguardando_regula"):
        numero_reg = re.sub(r"\D", "", texto)
        if not numero_reg:
            await update.message.reply_text("⚠️ Envie apenas os números da sua regulação.", reply_markup=TECLADO_MENU)
            return

        msg_aguarde = await update.message.reply_text("💾 <b>Cadastrando regulação...</b>", parse_mode="HTML")

        try:
            dados = {
                "id_do_chat": chat_id,
                "numero_reg": numero_reg,
                "status_anterior": "Pendente de primeira verificação"
            }
            supabase.table("AlertaSUS_2.0").insert(dados).execute()
            context.user_data["aguardando_regula"] = False

            await msg_aguarde.edit_text(
                f"✅ <b>Regulação <code>{escape(numero_reg)}</code> cadastrada com sucesso!</b>",
                reply_markup=TECLADO_MENU,
                parse_mode="HTML"
            )
        except Exception as error:
            logging.error(f"Erro ao cadastrar: {error}")
            await msg_aguarde.edit_text("⚠️ Erro ao salvar regulação. Tente novamente.", reply_markup=TECLADO_MENU)
        return

    await update.message.reply_text("🤖 Opção não reconhecida. Utilize o menu abaixo:", reply_markup=TECLADO_MENU)

async def configurar_menu_comandos(application):
    comandos = [
        BotCommand("start", "Iniciar bot e exibir menu principal"),
        BotCommand("verificar", "Consultar status das regulações"),
        BotCommand("cadastrar", "Cadastrar nova regulação"),
        BotCommand("corrigir", "Corrigir ID de regulação"),
        BotCommand("excluir", "Excluir regulação"),
        BotCommand("ajuda", "Central de ajuda")
    ]
    await application.bot.set_my_commands(comandos)