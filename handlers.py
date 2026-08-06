import re
import asyncio
import logging
from telegram import Update, BotCommand, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown
from config import supabase
from scraper import consultar_status_fms, montar_mensagem_regulacao

TECLADO_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📋 Consultar Todos"), KeyboardButton("➕ Cadastrar Nova")],
        [KeyboardButton("✏️ Corrigir ID"), KeyboardButton("❌ Excluir Regulação")],
        [KeyboardButton("ℹ️ Ajuda / Manual")]
    ],
    resize_keyboard=True
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    nome_usuario = update.effective_user.first_name or "Cidadão"
    mensagem = (
        f"👋 Olá, *{nome_usuario}*! Bem-vindo ao *AlertaSUS 2.0*!\n\n"
        "Escolha uma opção no menu abaixo para começar:"
    )
    await update.message.reply_text(mensagem, reply_markup=TECLADO_MENU, parse_mode="Markdown")

async def comando_ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    texto_ajuda = (
        "ℹ️ *Central de Ajuda - AlertaSUS 2.0*\n\n"
        "• Clique em *📋 Consultar Todos* para verificar suas regulações.\n"
        "• Clique em *➕ Cadastrar Nova* para incluir um novo ID de regulação.\n"
        "• Clique em *❌ Excluir Regulação* para remover um acompanhamento.\n\n"
        "⏰ *Varreduras automáticas:* Diariamente às 08:00 e 18:00."
    )
    await update.message.reply_text(texto_ajuda, reply_markup=TECLADO_MENU, parse_mode="Markdown")

async def comando_cadastrar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["aguardando_regula"] = True
    mensagem = (
        "📝 *Cadastro no AlertaSUS 2.0*\n\n"
        "Por favor, digite apenas o *Número da Regulação* (ID) que deseja monitorar.\n\n"
        "📌 *Exemplo:* `10829301`"
    )
    await update.message.reply_text(mensagem, reply_markup=TECLADO_MENU, parse_mode="Markdown")

async def comando_verificar_agora(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    msg_espera = await update.message.reply_text("🔍 *Consultando regulações no sistema...*", parse_mode="Markdown")

    try:
        resposta = await asyncio.to_thread(
            lambda: supabase.table("AlertaSUS_2.0").select("*").eq("id_do_chat", chat_id).execute()
        )
        regulacoes = resposta.data

        if not regulacoes:
            await msg_espera.edit_text(
                "ℹ️ Nenhuma regulação cadastrada para a sua conta.\nUtilize *➕ Cadastrar Nova* para registrar.",
                parse_mode="Markdown"
            )
            return

        for reg in regulacoes:
            numero_reg = reg.get("numero_reg")
            resultado = await consultar_status_fms(numero_reg)

            if resultado.get("sucesso"):
                mensagem = montar_mensagem_regulacao(
                    numero_reg,
                    resultado,
                    nome_paciente=reg.get("nome_paciente"),
                    data_nascimento=reg.get("data_nascimento"),
                    email=reg.get("email")
                )
                await update.message.reply_text(mensagem, parse_mode="Markdown")
            else:
                reg_esc = escape_markdown(str(numero_reg), version=1)
                await update.message.reply_text(f"❌ Erro ao consultar a regulação `{reg_esc}`.", parse_mode="Markdown")

        await msg_espera.delete()

    except Exception as e:
        logging.error(f"Erro no comando verificar: {e}")
        await msg_espera.edit_text("❌ Ocorreu um erro ao consultar suas regulações.")

async def comando_excluir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("⚠️ Informe o número da regulação. Ex: `/excluir 12345678`", parse_mode="Markdown")
        return

    numero_reg = re.sub(r"\D", "", context.args[0])
    try:
        supabase.table("AlertaSUS_2.0").delete().eq("id_do_chat", chat_id).eq("numero_reg", numero_reg).execute()
        await update.message.reply_text(f"✅ Regulação `{numero_reg}` excluída com sucesso!", parse_mode="Markdown")
    except Exception as error:
        logging.error(f"Erro ao excluir: {error}")
        await update.message.reply_text("⚠️ Falha ao remover a regulação.")

async def comando_corrigir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "✏️ Digite `/corrigir ID_ANTIGO ID_NOVO` para alterar um registro.\nExemplo: `/corrigir 12345678 87654321`",
        parse_mode="Markdown"
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

        msg_aguarde = await update.message.reply_text("💾 *Cadastrando regulação...*", parse_mode="Markdown")

        try:
            dados = {
                "id_do_chat": chat_id,
                "numero_reg": numero_reg,
                "status_anterior": "Pendente de primeira verificação"
            }
            supabase.table("AlertaSUS_2.0").insert(dados).execute()
            context.user_data["aguardando_regula"] = False

            await msg_aguarde.edit_text(
                f"✅ *Regulação `{numero_reg}` cadastrada com sucesso!*",
                reply_markup=TECLADO_MENU,
                parse_mode="Markdown"
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