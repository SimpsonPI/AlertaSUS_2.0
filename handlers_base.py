import logging
from html import escape
from telegram import Update, BotCommand
from telegram.ext import ContextTypes, ConversationHandler
from rate_limiter import rate_limit
from config import supabase
from scraper import consultar_status_fms

from handlers_utils import  (
    AVISO_PRIVADO_HTML,
    TECLADO_MENU,
    _buscar_regulacoes_db
)

async def verificar_se_e_menu_e_executar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Intercepta mensagens para atalhos de menu durante conversas ativas."""
    from handlers_cadastro import iniciar_cadastro_manual
    from handlers_consulta import comando_verificar_todas, iniciar_verificar_especifico
    from handlers_correcao import iniciar_corrigir
    from handlers_exclusao import iniciar_excluir

    if not update.message or not update.message.text:
        return False

    texto = update.message.text.strip()

    if "Cancelar" in texto or texto == "/cancelar":
        await cancelar_operacao(update, context)
        return True
    elif "Cadastrar Nova" in texto:
        await iniciar_cadastro_manual(update, context)
        return True
    elif "Verificar Todas" in texto:
        await comando_verificar_todas(update, context)
        return True
    elif "Verificar Específico" in texto:
        await iniciar_verificar_especifico(update, context)
        return True
    elif "Corrigir ID" in texto:
        await iniciar_corrigir(update, context)
        return True
    elif "Excluir Regulação" in texto:
        await iniciar_excluir(update, context)
        return True
    elif "Ajuda" in texto:
        await comando_ajuda(update, context)
        return True
    elif texto.startswith("/"):
        if texto.startswith("/start"):
            await start(update, context)
        elif texto.startswith("/ajuda"):
            await comando_ajuda(update, context)
        elif texto.startswith("/cadastrar"):
            await iniciar_cadastro_manual(update, context)
        elif texto.startswith("/verificar"):
            await comando_verificar_todas(update, context)
        elif texto.startswith("/consultar"):
            await iniciar_verificar_especifico(update, context)
        elif texto.startswith("/corrigir"):
            await iniciar_corrigir(update, context)
        elif texto.startswith("/excluir"):
            await iniciar_excluir(update, context)
        return True

    return False

@rate_limit(max_mensagens=5, janela_segundos=60)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    chat_id = update.effective_chat.id
    mensagem = (
        f"👋 Bem-vindo ao <b>AlertaSUS 2.0</b>!\n\n"
        f"🔑 <b>Seu ID do Chat:</b> <code>{chat_id}</code>\n\n"
        f"{AVISO_PRIVADO_HTML}\n\n"
        "Escolha uma opção no menu abaixo para começar:"
    )
    await update.message.reply_text(mensagem, reply_markup=TECLADO_MENU, parse_mode="HTML")
    return ConversationHandler.END

@rate_limit(max_mensagens=5, janela_segundos=60)
async def comando_ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    chat_id = update.effective_chat.id
    texto_ajuda = (
        "ℹ️ <b>Central de Ajuda - AlertaSUS 2.0</b>\n\n"
        f"🔑 <b>Seu ID do Chat:</b> <code>{chat_id}</code>\n\n"
        f"{AVISO_PRIVADO_HTML}\n\n"
        "• <b>➕ Cadastrar Nova:</b> Cadastre seus dados e ID de Regulação passo a passo.\n"
        "• <b>📋 Verificar Todas:</b> Consulta o status de todos os seus IDs cadastrados.\n"
        "• <b>🔍 Verificar Específico:</b> Consulta um único ID selecionado na lista.\n"
        "• <b>✏️ Corrigir ID:</b> Altera ID, Cartão SUS ou Nome de uma regulação de forma interativa.\n"
        "• <b>❌ Excluir Regulação:</b> Remove um ID mediante confirmação.\n\n"
        "⏰ <b>Varreduras automáticas:</b> Diariamente às 08:00 e 18:00."
    )
    await update.message.reply_text(texto_ajuda, reply_markup=TECLADO_MENU, parse_mode="HTML")
    return ConversationHandler.END

async def cancelar_operacao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ Operação cancelada.", reply_markup=TECLADO_MENU)
    return ConversationHandler.END

async def configurar_menu_comandos(application):
    comandos = [
        BotCommand("start", "Iniciar bot e exibir menu principal"),
        BotCommand("cadastrar", "Cadastrar nova regulação"),
        BotCommand("verificar", "Verificar todas as regulações"),
        BotCommand("consultar", "Verificar regulação específica"),
        BotCommand("corrigir", "Corrigir dados de regulação"),
        BotCommand("excluir", "Excluir regulação com confirmação"),
        BotCommand("ajuda", "Central de ajuda")
    ]
    await application.bot.set_my_commands(comandos)

async def executar_varredura_automatica(app):
    logging.info("⏰ Iniciando varredura automática de regulações...")
    try:
        import asyncio
        resp = await asyncio.to_thread(
            lambda: supabase.table("AlertaSUS_2.0").select("*").execute()
        )
        dados_regulacoes = getattr(resp, "data", []) or []

        for reg in dados_regulacoes:
            chat_id = reg.get("chat_id")
            numero_reg = str(reg.get("numero_reg", "")).strip()
            status_anterior = str(reg.get("status_anterior", "") or "").strip()
            nome_paciente = reg.get("nome_paciente", "Não informado")

            if not chat_id or not numero_reg:
                continue

            try:
                resultado = await consultar_status_fms(numero_reg)
                if resultado.get("sucesso"):
                    status_atual = str(resultado.get("status_resumido", "")).strip()

                    if status_anterior and status_atual != status_anterior:
                        await asyncio.to_thread(
                            lambda: supabase.table("AlertaSUS_2.0").update({
                                "status_anterior": status_atual
                            }).eq("chat_id", int(chat_id)).eq("numero_reg", str(numero_reg)).execute()
                        )

                        msg_alerta = (
                            f"🚨 <b>ALERTA DE ATUALIZAÇÃO!</b>\n\n"
                            f"📋 <b>Regulação:</b> <code>{escape(numero_reg)}</code>\n"
                            f"👤 <b>Paciente:</b> {escape(str(nome_paciente))}\n\n"
                            f"📊 <b>Novo Status:</b>\n{escape(status_atual)}"
                        )
                        await app.bot.send_message(
                            chat_id=int(chat_id),
                            text=msg_alerta,
                            parse_mode="HTML"
                        )
                        logging.info(f"Alerta enviado para Chat ID {chat_id} (Reg: {numero_reg})")
                    
                    elif not status_anterior:
                        await asyncio.to_thread(
                            lambda: supabase.table("AlertaSUS_2.0").update({
                                "status_anterior": status_atual
                            }).eq("chat_id", int(chat_id)).eq("numero_reg", str(numero_reg)).execute()
                        )

            except Exception as err_item:
                logging.error(f"Erro ao verificar regulação {numero_reg}: {err_item}")

    except Exception as e:
        logging.error(f"Erro geral na varredura automática: {e}")

async def abrir_link_cadastro(update, context):
    """Função legada para compatibilidade de importação."""
    pass