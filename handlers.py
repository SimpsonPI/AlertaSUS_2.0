import re
import asyncio
import logging
import traceback
from html import escape

from telegram import (
    Update,
    BotCommand,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo
)
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
)
from config import supabase, URL_FORMULARIO_PAGES
from scraper import consultar_status_fms, formatar_data_br, nome_paciente_exibicao

# Estados dos Fluxos Interativos
(
    CONSULTAR_ID,
    CORRIGIR_ANTIGO,
    CORRIGIR_NOVO,
    EXCLUIR_ID,
    EXCLUIR_CONFIRM,
) = range(5)

# Teclado Principal
TECLADO_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📋 Verificar Todas"), KeyboardButton("🔍 Verificar Específico")],
        [KeyboardButton("➕ Cadastrar Nova"), KeyboardButton("✏️ Corrigir ID")],
        [KeyboardButton("❌ Excluir Regulação"), KeyboardButton("ℹ️ Ajuda")]
    ],
    resize_keyboard=True
)

# Teclado de Cancelamento Rápido
TECLADO_CANCELAR = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🚫 Cancelar Operação")]
    ],
    resize_keyboard=True,
    one_time_keyboard=True
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

async def verificar_se_e_menu_e_executar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Intercepta cliques do menu ou cancelamentos durante conversas ativas."""
    if not update.message or not update.message.text:
        return False

    texto = update.message.text.strip()

    if "Cancelar" in texto or texto == "/cancelar":
        await cancelar_operacao(update, context)
        return True
    elif "Cadastrar Nova" in texto:
        await abrir_link_cadastro(update, context)
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
            await abrir_link_cadastro(update, context)
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

def _montar_msg_html(numero_reg: str, resultado: dict, reg_db: dict = None) -> str:
    """Monta a mensagem em HTML formatada apenas com Regulação, Paciente e Status."""
    dados = resultado.get("dados", {})
    
    # Busca o nome do paciente no resultado do scraper ou do banco de dados
    paciente = dados.get("paciente") or (reg_db.get("nome_paciente") if reg_db else None)
    if not paciente or str(paciente).strip().lower() in ["none", "null", ""]:
        paciente = "Não informado"
    
    # Status retornado pelo scraper
    status = resultado.get("status_resumido", "Pendente")

    return (
        f"📋 <b>Regulação:</b> <code>{escape(numero_reg)}</code>\n"
        f"👤 <b>Paciente:</b> {escape(str(paciente))}\n"
        f"📊 <b>Status:</b> {escape(str(status))}"
    )

async def _buscar_regulacao_por_id_reg(numero_reg: str) -> dict:
    """Busca uma regulação específica no Supabase pelo número da regulação."""
    try:
        resp = await asyncio.to_thread(
            lambda: supabase.table("AlertaSUS_2.0").select("*").eq("numero_reg", str(numero_reg)).execute()
        )
        if resp and getattr(resp, "data", None) and len(resp.data) > 0:
            return resp.data[0]
    except Exception as e:
        logging.error(f"Erro ao buscar regulação por ID ({numero_reg}): {e}")
    return {}

async def _buscar_regulacoes_db(chat_id: int) -> list:
    """Busca todas as regulações do usuário no Supabase sem depender do nome exato da coluna."""
    str_chat_id = str(chat_id).strip()
    try:
        # Puxa os dados da tabela no Supabase
        resp = await asyncio.to_thread(
            lambda: supabase.table("AlertaSUS_2.0").select("*").execute()
        )
        
        if resp and getattr(resp, "data", None):
            regulacoes_usuario = []
            for row in resp.data:
                # Transforma todos os valores da linha em texto e verifica se o seu chat_id está entre eles
                valores_linha = [str(val).strip() for val in row.values()]
                if str_chat_id in valores_linha:
                    regulacoes_usuario.append(row)
            
            return regulacoes_usuario

    except Exception as e:
        logging.error(f"Erro ao consultar Supabase: {e}")

    return []

# --- COMANDOS BÁSICOS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    chat_id = update.effective_chat.id
    mensagem = (
        f"👋 Bem-vindo ao <b>AlertaSUS 2.0</b>!\n\n"
        f"🔑 <b>Seu ID do Chat:</b> <code>{chat_id}</code>\n\n"
        "Escolha uma opção no menu abaixo para começar:"
    )
    await update.message.reply_text(mensagem, reply_markup=TECLADO_MENU, parse_mode="HTML")
    return ConversationHandler.END

async def comando_ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    chat_id = update.effective_chat.id
    texto_ajuda = (
        "ℹ️ <b>Central de Ajuda - AlertaSUS 2.0</b>\n\n"
        f"🔑 <b>Seu ID do Chat:</b> <code>{chat_id}</code>\n\n"
        "• <b>➕ Cadastrar Nova:</b> Acesse o formulário interno no Telegram.\n"
        "• <b>📋 Verificar Todas:</b> Consulta o status de todos os seus IDs cadastrados.\n"
        "• <b>🔍 Verificar Específico:</b> Consulta um único ID informado na hora.\n"
        "• <b>✏️ Corrigir ID:</b> Altera um ID antigo para um novo ID.\n"
        "• <b>❌ Excluir Regulação:</b> Remove um ID mediante confirmação.\n\n"
        "⏰ <b>Varreduras automáticas:</b> Diariamente às 08:00 e 18:00."
    )
    await update.message.reply_text(texto_ajuda, reply_markup=TECLADO_MENU, parse_mode="HTML")
    return ConversationHandler.END

async def cancelar_operacao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ Operação cancelada.", reply_markup=TECLADO_MENU)
    return ConversationHandler.END

# --- 1. CADASTRAR NOVA (WEB APP DENTRO DO BOT) ---

async def abrir_link_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    chat_id = update.effective_chat.id
    
    link_com_parametro = f"{URL_FORMULARIO_PAGES}?chat_id={chat_id}"

    teclado_webapp = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Abrir Formulário no Bot", web_app=WebAppInfo(url=link_com_parametro))]
    ])

    mensagem = (
        "📝 <b>Formulário de Cadastro</b>\n\n"
        f"🔑 <b>Seu ID do Chat:</b> <code>{chat_id}</code>\n\n"
        "Clique no botão abaixo para abrir e preencher o formulário diretamente dentro do Telegram:"
    )
    await update.message.reply_text(
        mensagem,
        reply_markup=teclado_webapp,
        parse_mode="HTML"
    )
    return ConversationHandler.END

# --- 2. VERIFICAR TODAS ---

async def comando_verificar_todas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    chat_id = update.effective_chat.id
    msg_espera = await update.message.reply_text("🔍 <b>Consultando suas regulações no sistema...</b>", parse_mode="HTML")

    try:
        regulacoes = await _buscar_regulacoes_db(chat_id)

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

    except Exception as e:
        logging.error(f"Erro ao consultar regulações: {traceback.format_exc()}")
        await msg_espera.edit_text("❌ Ocorreu um erro ao acessar o banco de dados. Tente novamente em instantes.")

    return ConversationHandler.END

# --- 3. VERIFICAR ESPECÍFICO ---

async def iniciar_verificar_especifico(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "🔍 Digite o <b>Número da Regulação (ID)</b> que deseja consultar agora:",
        reply_markup=TECLADO_CANCELAR,
        parse_mode="HTML"
    )
    return CONSULTAR_ID

async def processar_verificar_especifico(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    texto = update.message.text
    numero_reg = re.sub(r"\D", "", texto)

    if not numero_reg:
        await update.message.reply_text("⚠️ Por favor, digite apenas os números do ID da regulação:", reply_markup=TECLADO_CANCELAR)
        return CONSULTAR_ID

    msg_espera = await update.message.reply_text(f"🔎 Pesquisando ID <code>{escape(numero_reg)}</code>...", parse_mode="HTML")

    reg_db = await _buscar_regulacao_por_id_reg(numero_reg)
    resultado = await consultar_status_fms(numero_reg)

    await msg_espera.delete()

    if resultado.get("sucesso"):
        msg_html = _montar_msg_html(numero_reg, resultado, reg_db)
        await update.message.reply_text(msg_html, parse_mode="HTML", reply_markup=TECLADO_MENU)
    else:
        msg_erro = resultado.get("mensagem") or "Regulação não encontrada na FMS."
        await update.message.reply_text(f"❌ {escape(msg_erro)}", parse_mode="HTML", reply_markup=TECLADO_MENU)

    context.user_data.clear()
    return ConversationHandler.END

# --- 4. CORRIGIR ID ---

async def iniciar_corrigir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "✏️ <b>Passo 1 de 2:</b> Digite o <b>ID da Regulação ANTIGO</b> que você quer alterar:",
        reply_markup=TECLADO_CANCELAR,
        parse_mode="HTML"
    )
    return CORRIGIR_ANTIGO

async def processar_corrigir_antigo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    texto = update.message.text
    id_antigo = re.sub(r"\D", "", texto)
    if not id_antigo:
        await update.message.reply_text("⚠️ Digite um ID numérico válido:", reply_markup=TECLADO_CANCELAR)
        return CORRIGIR_ANTIGO

    context.user_data["id_antigo"] = id_antigo
    await update.message.reply_text(
        f"✏️ <b>Passo 2 de 2:</b> Digite o <b>NOVO ID</b> para substituir o ID <code>{escape(id_antigo)}</code>:",
        reply_markup=TECLADO_CANCELAR,
        parse_mode="HTML"
    )
    return CORRIGIR_NOVO

async def processar_corrigir_novo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    texto = update.message.text
    id_novo = re.sub(r"\D", "", texto)
    chat_id = update.effective_chat.id
    id_antigo = context.user_data.get("id_antigo")

    if not id_novo:
        await update.message.reply_text("⚠️ Digite um ID numérico válido:", reply_markup=TECLADO_CANCELAR)
        return CORRIGIR_NOVO

    try:
        resultado_fms = await consultar_status_fms(id_novo)
        novo_status = resultado_fms.get("status_resumido", "Pendente") if resultado_fms.get("sucesso") else "Atualizado"

        resp = await asyncio.to_thread(
            lambda: supabase.table("AlertaSUS_2.0").update({
                "numero_reg": id_novo,
                "status_anterior": novo_status
            }).eq("chat_id", int(chat_id)).eq("numero_reg", str(id_antigo)).execute()
        )

        if resp and getattr(resp, "data", None):
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

# --- 5. EXCLUIR REGULAÇÃO ---

async def iniciar_excluir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    chat_id = update.effective_chat.id

    regs = await _buscar_regulacoes_db(chat_id)

    if not regs:
        await update.message.reply_text("ℹ️ Você não possui nenhuma regulação cadastrada para excluir.", reply_markup=TECLADO_MENU)
        return ConversationHandler.END

    itens_formatados = []
    for r in regs:
        num = str(r.get("numero_reg") or "Sem ID").strip()
        nome = r.get("nome_paciente") or "Sem nome"
        itens_formatados.append(f"• <code>{escape(num)}</code> - {escape(nome)}")

    lista_txt = "\n".join(itens_formatados)
    await update.message.reply_text(
        f"❌ <b>Exclusão de Regulação</b>\n\n"
        f"Suas regulações salvas:\n{lista_txt}\n\n"
        f"Digite o <b>Número da Regulação (ID)</b> que deseja excluir:",
        reply_markup=TECLADO_CANCELAR,
        parse_mode="HTML"
    )
    return EXCLUIR_ID

async def processar_excluir_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    texto = update.message.text
    id_excluir = re.sub(r"\D", "", texto)

    if not id_excluir:
        await update.message.reply_text("⚠️ Informe um ID de regulação numérico válido:", reply_markup=TECLADO_CANCELAR)
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
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    texto = update.message.text.strip()
    chat_id = update.effective_chat.id
    id_excluir = context.user_data.get("id_excluir")

    if "Sim" in texto:
        try:
            res = await asyncio.to_thread(
                lambda: supabase.table("AlertaSUS_2.0").delete().eq("chat_id", int(chat_id)).eq("numero_reg", str(id_excluir)).execute()
            )
            if res and getattr(res, "data", None):
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
        except Exception as e:
            logging.error(f"Erro ao excluir ID {id_excluir}: {e}")
            await update.message.reply_text("❌ Erro ao excluir do banco de dados.", reply_markup=TECLADO_MENU)
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
    # ------------------------------------------------------------------
# NOVO TRECHO: Adicionar este bloco ao final do arquivo handlers.py
# ------------------------------------------------------------------

async def executar_varredura_automatica(app):
    """Varre todas as regulações cadastradas e notifica os usuários sobre mudanças de status."""
    logging.info("⏰ Iniciando varredura automática de regulações...")
    try:
        # Busca todas as regulações cadastradas no Supabase
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

                    # Se o status mudou em relação à consulta anterior
                    if status_anterior and status_atual != status_anterior:
                        # 1. Atualiza o novo status no banco de dados
                        await asyncio.to_thread(
                            lambda: supabase.table("AlertaSUS_2.0").update({
                                "status_anterior": status_atual
                            }).eq("chat_id", int(chat_id)).eq("numero_reg", str(numero_reg)).execute()
                        )

                        # 2. Envia a notificação direta no Telegram
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
                        # Registra o primeiro status caso estivesse em branco
                        await asyncio.to_thread(
                            lambda: supabase.table("AlertaSUS_2.0").update({
                                "status_anterior": status_atual
                            }).eq("chat_id", int(chat_id)).eq("numero_reg", str(numero_reg)).execute()
                        )

            except Exception as err_item:
                logging.error(f"Erro ao verificar regulação {numero_reg}: {err_item}")

    except Exception as e:
        logging.error(f"Erro geral na varredura automática: {e}")