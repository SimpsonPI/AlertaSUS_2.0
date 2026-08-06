import re
import asyncio
import logging
import traceback
from html import escape

from telegram import Update, BotCommand, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
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

# URL do Formulário
URL_FORMULARIO_PAGES = "https://simpsonpi.github.io/alerta-sus-bot/"

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

async def verificar_se_e_menu_e_executar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Detecta se o usuário clicou em um botão do menu durante um fluxo e executa a ação imediatamente."""
    if not update.message or not update.message.text:
        return False

    texto = update.message.text.strip()

    if "Cadastrar Nova" in texto:
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
    elif "Excluir Regulação" in texto or "Excluir" in texto:
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
        elif texto.startswith("/cancelar"):
            await cancelar_operacao(update, context)
        return True

    return False

def _obter_campo(d: dict | None, *chaves, padrao="Não informado") -> str:
    """Extrai o primeiro valor válido encontrado no dicionário baseado nas chaves passadas."""
    if not d:
        return padrao
    for k in chaves:
        val = d.get(k)
        if val is not None and str(val).strip() != "":
            return str(val).strip()
    return padrao

async def _buscar_regulacoes_db(chat_id: int) -> list:
    """Busca as regulações no Supabase testando diferentes nomes de coluna e tipos de dados."""
    colunas_chat = ["id_do_chat", "chat_id"]
    valores_chat = [chat_id, str(chat_id)]

    for col in colunas_chat:
        for val in valores_chat:
            try:
                resp = await asyncio.to_thread(
                    lambda c=col, v=val: supabase.table("AlertaSUS_2.0").select("*").eq(c, v).execute()
                )
                if resp and hasattr(resp, "data") and resp.data:
                    logging.info(f"Busca DB bem-sucedida ({col}={val}): {len(resp.data)} registros encontrados.")
                    return resp.data
            except Exception as e:
                logging.warning(f"Tentativa de busca DB ({col}={val}) falhou: {e}")

    try:
        resp = await asyncio.to_thread(
            lambda: supabase.table("AlertaSUS_2.0").select("*").execute()
        )
        if resp and hasattr(resp, "data") and resp.data:
            filtrados = [
                r for r in resp.data
                if str(r.get("id_do_chat") or r.get("chat_id") or "").strip() == str(chat_id)
            ]
            return filtrados
    except Exception as e:
        logging.error(f"Erro no fallback geral do banco de dados: {e}")

    return []

def _montar_msg_html(numero_reg: str, resultado: dict, reg_db: dict | None = None) -> str:
    """Gera a mensagem de status formatada em HTML extraindo os dados com fallback de chaves."""
    reg_db = reg_db or {}

    nome_bruto = _obter_campo(reg_db, "nome_paciente", "nome", "paciente")
    nome = escape(nome_paciente_exibicao(nome_bruto))

    dt_bruta = _obter_campo(reg_db, "data_nascimento", "data_nasc", "nascimento")
    dt_nasc = escape(formatar_data_br(dt_bruta))

    email = escape(_obter_campo(reg_db, "email", "e-mail", "mail"))
    celular = escape(_obter_campo(reg_db, "celular", "whatsapp", "telefone", "phone"))
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
    context.user_data.clear()
    mensagem = (
        "👋 Bem-vindo ao <b>AlertaSUS 2.0</b>!\n\n"
        "Escolha uma opção no menu abaixo para começar:"
    )
    await update.message.reply_text(mensagem, reply_markup=TECLADO_MENU, parse_mode="HTML")
    return ConversationHandler.END

async def comando_ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
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

# --- 1. CADASTRAR NOVA ---

async def abrir_link_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    mensagem = (
        "📝 <b>Formulário de Cadastro</b>\n\n"
        "Para cadastrar uma nova regulação, acesse o formulário no link abaixo:\n\n"
        f"🔗 <a href='{URL_FORMULARIO_PAGES}'>Clique aqui para abrir o Formulário de Cadastro</a>"
    )
    await update.message.reply_text(
        mensagem,
        reply_markup=TECLADO_MENU,
        parse_mode="HTML",
        disable_web_page_preview=True
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
            numero_reg = str(reg.get("numero_reg") or reg.get("numero_regulacao") or "").strip()
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
    context.user_data.clear()
    await update.message.reply_text(
        "🔍 Digite o <b>Número da Regulação (ID)</b> que deseja consultar agora:\n\n"
        "<i>(Ou digite /cancelar para sair)</i>",
        parse_mode="HTML"
    )
    return CONSULTAR_ID

async def processar_verificar_especifico(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    texto = update.message.text
    numero_reg = re.sub(r"\D", "", texto)
    chat_id = update.effective_chat.id

    if not numero_reg:
        await update.message.reply_text("⚠️ Por favor, digite apenas os números do ID da regulação:")
        return CONSULTAR_ID

    msg_espera = await update.message.reply_text(f"🔎 Pesquisando ID <code>{escape(numero_reg)}</code> na FMS...", parse_mode="HTML")

    reg_db = None
    try:
        regs = await _buscar_regulacoes_db(chat_id)
        for r in regs:
            id_no_banco = str(r.get("numero_reg") or r.get("numero_regulacao") or "").strip()
            if id_no_banco == numero_reg:
                reg_db = r
                break
    except Exception as err:
        logging.warning(f"Aviso de busca de regulação específica no DB: {err}")

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
        "✏️ <b>Passo 1 de 2:</b> Digite o <b>ID da Regulação ANTIGO</b> que você quer alterar:\n\n"
        "<i>(Ou digite /cancelar para sair)</i>",
        parse_mode="HTML"
    )
    return CORRIGIR_ANTIGO

async def processar_corrigir_antigo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    texto = update.message.text
    id_antigo = re.sub(r"\D", "", texto)
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
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    texto = update.message.text
    id_novo = re.sub(r"\D", "", texto)
    chat_id = update.effective_chat.id
    id_antigo = context.user_data.get("id_antigo")

    if not id_novo:
        await update.message.reply_text("⚠️ Digite um ID numérico válido para o novo código:")
        return CORRIGIR_NOVO

    try:
        resultado_fms = await consultar_status_fms(id_novo)
        novo_status = resultado_fms.get("status_resumido", "Pendente") if resultado_fms.get("sucesso") else "Atualizado"

        alterou = False
        colunas_chat = ["id_do_chat", "chat_id"]
        valores_chat = [chat_id, str(chat_id)]
        colunas_reg = ["numero_reg", "numero_regulacao"]

        for col_c in colunas_chat:
            for val_c in valores_chat:
                for col_r in colunas_reg:
                    try:
                        resp = await asyncio.to_thread(
                            lambda c_c=col_c, v_c=val_c, c_r=col_r: supabase.table("AlertaSUS_2.0").update({
                                "numero_reg": id_novo,
                                "status_anterior": novo_status
                            }).eq(c_c, v_c).eq(c_r, id_antigo).execute()
                        )
                        if resp and getattr(resp, "data", None):
                            alterou = True
                            break
                    except Exception:
                        pass
                if alterou:
                    break
            if alterou:
                break

        if alterou:
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
        num = str(r.get("numero_reg") or r.get("numero_regulacao") or "Sem ID").strip()
        nome = _obter_campo(r, "nome_paciente", "nome", "paciente", padrao="Sem nome")
        itens_formatados.append(f"• <code>{escape(num)}</code> - {escape(nome)}")

    lista_txt = "\n".join(itens_formatados)
    await update.message.reply_text(
        f"❌ <b>Exclusão de Regulação</b>\n\n"
        f"Suas regulações salvas:\n{lista_txt}\n\n"
        f"Digite o <b>Número da Regulação (ID)</b> que deseja excluir:\n"
        f"<i>(Ou digite /cancelar para sair)</i>",
        parse_mode="HTML"
    )
    return EXCLUIR_ID

async def processar_excluir_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    texto = update.message.text
    id_excluir = re.sub(r"\D", "", texto)

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
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    texto = update.message.text.strip()
    chat_id = update.effective_chat.id
    id_excluir = context.user_data.get("id_excluir")

    if "Sim" in texto:
        excluiu = False
        colunas_chat = ["id_do_chat", "chat_id"]
        valores_chat = [chat_id, str(chat_id)]
        colunas_reg = ["numero_reg", "numero_regulacao"]

        for col_c in colunas_chat:
            for val_c in valores_chat:
                for col_r in colunas_reg:
                    try:
                        res = await asyncio.to_thread(
                            lambda c_c=col_c, v_c=val_c, c_r=col_r: supabase.table("AlertaSUS_2.0").delete().eq(c_c, v_c).eq(c_r, id_excluir).execute()
                        )
                        if res and getattr(res, "data", None):
                            excluiu = True
                            break
                    except Exception:
                        pass
                if excluiu:
                    break
            if excluiu:
                break

        if excluiu:
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