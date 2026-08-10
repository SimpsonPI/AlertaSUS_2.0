import re
import asyncio
import logging
from html import escape
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from rate_limiter import rate_limit
from config import supabase
from scraper import consultar_status_fms

from handlers_utils import (
    ETAPA_SUS, ETAPA_NOME, ETAPA_CELULAR, ETAPA_NASCIMENTO,
    ETAPA_REGULACAO, ETAPA_CBO, ETAPA_PROCEDIMENTO, ETAPA_LGPD,
    TECLADO_MENU, TECLADO_CANCELAR,
    limpar_telefone, formatar_data_nascimento, para_maiusculo,
    _buscar_paciente_por_sus
)
from handlers)base import verificar_se_e_menu_e_executar

@rate_limit(max_mensagens=5, janela_segundos=60)
async def iniciar_cadastro_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    msg = (
        "📝 <b>Cadastro de Alerta SUS</b>\n\n"
        "1️⃣ Digite o seu <b>Número do Cartão SUS</b>:\n"
        "<i>(Apenas os 15 números do cartão)</i>"
    )
    await update.message.reply_text(msg, reply_markup=TECLADO_CANCELAR, parse_mode="HTML")
    return ETAPA_SUS

async def receber_sus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    numero_sus = re.sub(r"\D", "", update.message.text.strip())

    if not numero_sus:
        await update.message.reply_text("⚠️ Por favor, digite apenas números para o Cartão SUS:")
        return ETAPA_SUS

    context.user_data['numero_sus'] = numero_sus
    
    msg_aguarde = await update.message.reply_text("🔍 <i>Verificando dados do Cartão SUS no sistema...</i>", parse_mode="HTML")
    paciente_existente = await _buscar_paciente_por_sus(numero_sus)
    await msg_aguarde.delete()

    if paciente_existente and paciente_existente.get("nome_paciente"):
        context.user_data['nome_paciente'] = paciente_existente.get("nome_paciente")
        context.user_data['celular'] = paciente_existente.get("celular")
        context.user_data['data_nascimento'] = paciente_existente.get("data_nascimento")

        await update.message.reply_text(
            f"✅ <b>Paciente Encontrado!</b>\n\n"
            f"👤 <b>Nome:</b> {escape(str(context.user_data['nome_paciente']))}\n"
            f"📱 <b>Celular:</b> {escape(str(context.user_data['celular'] or 'N/I'))}\n"
            f"📅 <b>Nascimento:</b> {escape(str(context.user_data['data_nascimento'] or 'N/I'))}\n\n"
            f"2️⃣ Digite o <b>Número de Regulação (ID)</b> para esta consulta:",
            parse_mode="HTML",
            reply_markup=TECLADO_CANCELAR
        )
        return ETAPA_REGULACAO
    else:
        await update.message.reply_text(
            "ℹ️ Cartão SUS não localizado em cadastros anteriores.\n\n"
            "2️⃣ Por favor, digite o <b>Nome Completo do Paciente</b>:",
            parse_mode="HTML",
            reply_markup=TECLADO_CANCELAR
        )
        return ETAPA_NOME

async def receber_nome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    nome_formatado = para_maiusculo(update.message.text)
    context.user_data["nome_paciente"] = nome_formatado

    await update.message.reply_text(
        "3️⃣ Qual o <b>Celular / WhatsApp</b> com DDD?\n<i>Digite apenas os números (ex: 86999999999)</i>",
        reply_markup=TECLADO_CANCELAR,
        parse_mode="HTML"
    )
    return ETAPA_CELULAR

async def receber_celular(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    celular_limpo = limpar_telefone(update.message.text)

    if len(celular_limpo) not in (10, 11):
        await update.message.reply_text(
            "⚠️ <b>Telefone inválido!</b>\nDigite apenas os números com DDD (ex: <code>86999999999</code>):",
            reply_markup=TECLADO_CANCELAR,
            parse_mode="HTML"
        )
        return ETAPA_CELULAR

    context.user_data["celular"] = celular_limpo

    await update.message.reply_text(
        "4️⃣ Qual a <b>Data de Nascimento</b>?\n<i>Digite apenas os 8 números (ex: 15081990)</i>",
        reply_markup=TECLADO_CANCELAR,
        parse_mode="HTML"
    )
    return ETAPA_NASCIMENTO

async def receber_nascimento(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    texto_data = update.message.text
    data_formatada = formatar_data_nascimento(texto_data)

    if not data_formatada:
        await update.message.reply_text(
            "⚠️ <b>Data de Nascimento inválida!</b>\nDigite apenas os 8 números no formato DDMMAAAA (ex: <code>15081990</code>):",
            reply_markup=TECLADO_CANCELAR,
            parse_mode="HTML"
        )
        return ETAPA_NASCIMENTO

    context.user_data["data_nascimento"] = data_formatada

    await update.message.reply_text(
        "5️⃣ Digite o <b>Número de Regulação (ID)</b>:\n<i>(Apenas números, ex: 12345678)</i>",
        reply_markup=TECLADO_CANCELAR,
        parse_mode="HTML"
    )
    return ETAPA_REGULACAO

async def receber_regulacao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    regulacao = re.sub(r"\D", "", update.message.text.strip())
    
    if not regulacao:
        await update.message.reply_text("⚠️ Por favor, digite apenas números para o ID de Regulação:")
        return ETAPA_REGULACAO

    context.user_data['numero_reg'] = regulacao
    
    msg_aguarde = await update.message.reply_text("🔍 <i>Buscando informações da regulação no SUS...</i>", parse_mode="HTML")
    try:
        resultado = await consultar_status_fms(regulacao)
        if resultado and resultado.get("sucesso"):
            context.user_data['status_inicial'] = resultado.get("status_resumido", "Consulta realizada")
            dados_fms = resultado.get("dados", {})
            if dados_fms.get("procedimento"):
                context.user_data['procedimento_sugerido'] = dados_fms.get("procedimento")
        else:
            context.user_data['status_inicial'] = "Cadastrado / Aguardando FMS"
    except Exception as e:
        logging.error(f"Erro ao consultar FMS no cadastro: {e}")
        context.user_data['status_inicial'] = "Cadastrado / Aguardando FMS"

    await msg_aguarde.delete()

    await update.message.reply_text(
        "📌 Digite o <b>CBO</b> (Código ou Nome da Especialidade/Ocupação):\n<i>Ex: Clínico Geral, Cardiologia, 225125...</i>",
        reply_markup=TECLADO_CANCELAR,
        parse_mode="HTML"
    )
    return ETAPA_CBO

async def receber_cbo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    context.user_data["cbo"] = para_maiusculo(update.message.text)
    
    procedimento_sugerido = context.user_data.get("procedimento_sugerido", "")
    msg_extra = f"\n<i>(Identificado na FMS: {procedimento_sugerido})</i>" if procedimento_sugerido else ""

    await update.message.reply_text(
        f"📑 Digite o Nome do <b>PROCEDIMENTO</b> ou Exame:{msg_extra}",
        reply_markup=TECLADO_CANCELAR,
        parse_mode="HTML"
    )
    return ETAPA_PROCEDIMENTO

async def receber_procedimento(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    context.user_data["procedimento"] = para_maiusculo(update.message.text)

    termo_lgpd = (
        "<b>🔒 Termo de Consentimento (LGPD)</b>\n\n"
        "Ao confirmar, você autoriza o AlertaSUS a utilizar seus dados para consultar "
        "sua posição na fila do SUS e enviar alertas pelo Telegram. Seus dados são protegidos e não serão compartilhados.\n\n"
        "Você concorda com estes termos?"
    )
    
    teclado_lgpd = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Sim, Concordo e Ativar", callback_data="aceitar_lgpd")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_cadastro")]
    ])
    
    await update.message.reply_text(termo_lgpd, reply_markup=teclado_lgpd, parse_mode="HTML")
    return ETAPA_LGPD

async def finalizar_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancelar_cadastro":
        await query.message.edit_text("❌ Cadastro cancelado.")
        await query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)
        context.user_data.clear()
        return ConversationHandler.END

    chat_id = update.effective_chat.id
    dados = {
        "chat_id": int(chat_id),
        "numero_sus": str(context.user_data.get("numero_sus")),
        "numero_reg": str(context.user_data.get("numero_reg")),
        "nome_paciente": str(context.user_data.get("nome_paciente")),
        "celular": context.user_data.get("celular"),
        "data_nascimento": context.user_data.get("data_nascimento"),
        "cbo": context.user_data.get("cbo"),
        "procedimento": context.user_data.get("procedimento"),
        "status_anterior": context.user_data.get("status_inicial", "Cadastrado")
    }

    try:
        await asyncio.to_thread(
            lambda: supabase.table("AlertaSUS_2.0").insert(dados).execute()
        )
        await query.message.edit_text(
            f"🎉 <b>Alertas Ativados com Sucesso!</b>\n\n"
            f"🆔 <b>Cartão SUS:</b> <code>{escape(str(dados['numero_sus']))}</code>\n"
            f"📌 <b>ID de Regulação:</b> <code>{escape(str(dados['numero_reg']))}</code>\n"
            f"👤 <b>Paciente:</b> {escape(str(dados['nome_paciente']))}\n"
            f"🩺 <b>CBO:</b> {escape(str(dados['cbo']))}\n"
            f"📑 <b>Procedimento:</b> {escape(str(dados['procedimento']))}\n\n"
            f"Avisaremos você aqui no chat assim que a sua posição mudar na fila!",
            parse_mode="HTML"
        )
        await query.message.reply_text("O que deseja fazer agora?", reply_markup=TECLADO_MENU)
    except Exception as e:
        logging.error(f"Erro ao salvar no Supabase: {e}")
        await query.message.edit_text("⚠️ Ocorreu um erro ao salvar o cadastro. Tente novamente mais tarde.")
        await query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)

    context.user_data.clear()
    return ConversationHandler.END