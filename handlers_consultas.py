


# handlers_consultas.py
import logging
import re
from html import escape
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from scraper import consultar_status_fms
from database import (
    buscar_regulacoes_por_chat_id as buscar_regulacoes_por_usuario,
    obter_regulacao_por_numero
)
from utils import (
    DISCLAIMER_TEXTO, TECLADO_MENU, TECLADO_CANCELAR, CONSULTAR_ID,
    _extrair_id_e_nome, mascarar_nome, verificar_se_e_menu_e_executar
)

logger = logging.getLogger(__name__)

def _mascarar_nome_custom(nome: str) -> str:
    """Retorna: Primeiro nome + iniciais. Ex: 'João Silva Santos' -> 'João S. S.'"""
    if not nome or str(nome).lower() in ["none", "não informado", ""]:
        return "Não informado"
    partes = nome.strip().split()
    if len(partes) <= 1:
        return partes[0].capitalize()
    
    primeiro = partes[0].capitalize()
    iniciais = [f"{p[0].upper()}." for p in partes[1:]]
    return f"{primeiro} {' '.join(iniciais)}"

def _mascarar_sus_custom(sus: str) -> str:
    """Retorna: 3 primeiros + 3 últimos. Ex: '12345678912' -> '123*****912'"""
    s = str(sus).strip()
    if len(s) < 6:
        return s
    return f"{s[:3]}{'*' * 5}{s[-3:]}"

def _montar_msg_html(num_reg: str, resultado: dict, reg_db=None) -> str:
    """
    Gera a mensagem formatada em HTML para exibição no Telegram.
    Prioriza avisos/orientações do portal da FMS em relação à 'Posição na Fila'.
    """
    cartao_sus_raw = ""
    nome_paciente_raw = ""
    cbo = "Não informado"
    procedimento = "Não informado"

    # Extração de dados cadastrais salvos na base local / Supabase
    if reg_db:
        if isinstance(reg_db, dict):
            cartao_sus_raw = reg_db.get("numero_sus") or reg_db.get("cartao_sus") or ""
            nome_paciente_raw = reg_db.get("nome_paciente") or ""
            cbo = reg_db.get("cbo") or cbo
            procedimento = reg_db.get("procedimento") or procedimento

    # Aplicação de Máscaras
    nome_exibicao = _mascarar_nome_custom(nome_paciente_raw)
    cartao_sus_exibicao = _mascarar_sus_custom(cartao_sus_raw) if cartao_sus_raw else "Não informado"

    # Processamento do retorno do scraper / FMS
    if isinstance(resultado, dict) and resultado.get("sucesso"):
        situacao = resultado.get("situacao") or "Informada no portal"
        posicao = resultado.get("posicao_fila") or "Não informada"
        previsao = resultado.get("previsao_atendimento") or "Não informada"
        alerta = resultado.get("alerta_fms") or resultado.get("alerta")
        data_consulta = resultado.get("data_consulta")
        estabelecimento = resultado.get("estabelecimento")
        endereco = resultado.get("endereco")
        telefone = resultado.get("telefone")
    else:
        situacao = "Não encontrada / Indisponível"
        posicao = "Não informada"
        previsao = "Não informada"
        alerta = resultado.get("mensagem") if isinstance(resultado, dict) else None
        data_consulta = None
        estabelecimento = None
        endereco = None
        telefone = None

    linhas = [
        "📋 <b>STATUS DA REGULAÇÃO</b>",
        "",
        f"<b>ID Regulação:</b> <code>{escape(str(num_reg))}</code>",
        f"<b>Cartão SUS:</b> <code>{escape(str(cartao_sus_exibicao))}</code>",
        f"<b>Paciente:</b> {escape(str(nome_exibicao))}",
        f"<b>CBO:</b> {escape(str(cbo).upper())}",
        f"<b>Procedimento:</b> {escape(str(procedimento).upper())}",
        f"<b>Status:</b> {escape(str(situacao))}",
    ]

    # Caso exista agendamento confirmado
    if data_consulta or estabelecimento:
        linhas.append("")
        linhas.append("📅 <b>DADOS DO AGENDAMENTO</b>")
        if data_consulta:
            linhas.append(f"• <b>Data/Hora:</b> {escape(str(data_consulta))}")
        if estabelecimento:
            linhas.append(f"• <b>Local:</b> {escape(str(estabelecimento))}")
        if endereco:
            linhas.append(f"• <b>Endereço:</b> {escape(str(endereco))}")
        if telefone:
            linhas.append(f"• <b>Telefone:</b> {escape(str(telefone))}")

        if alerta and str(alerta).strip():
            linhas.append("")
            linhas.append(f"⚠️ <b>AVISO DO PORTAL:</b>\n<i>{escape(str(alerta.strip()))}</i>")
    else:
        # Se houver mensagem/aviso do portal (ex: cancelamento, comparecimento à UBS), exibe em destaque
        if alerta and str(alerta).strip():
            linhas.append("")
            linhas.append(f"⚠️ <b>Mensagem do Portal:</b>\n<i>{escape(str(alerta.strip()))}</i>")
        elif previsao and previsao != "Não informada":
            linhas.append(f"<b>Previsão:</b> {escape(str(previsao))}")
        else:
            linhas.append(f"<b>Posição na Fila:</b> {escape(str(posicao))}")

    if DISCLAIMER_TEXTO:
        linhas.append("")
        linhas.append(f"ℹ️ <i>{DISCLAIMER_TEXTO.strip()}</i>")

    return "\n".join(linhas)

async def _buscar_regulacao_por_id_reg(numero_reg: str):
    try:
        res = obter_regulacao_por_numero(numero_reg)
        return await res if hasattr(res, "__await__") else res
    except Exception as e:
        logger.error(f"Erro ao buscar regulação {numero_reg}: {e}")
        return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data.clear()
    mensagem = (
        f"Olá, <b>{escape(user.first_name)}</b>! 👋\n\n"
        f"Bem-vindo ao <b>AlertaSUS 2.0</b>.\n"
        f"Eu ajudo você a acompanhar o status de suas regulações na FMS Piauí em tempo real.\n\n"
        f"{DISCLAIMER_TEXTO}\n\nEscolha uma opção no menu abaixo para começar:"
    )
    await update.message.reply_text(mensagem, parse_mode="HTML", reply_markup=TECLADO_MENU)

async def comando_ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensagem = (
        "ℹ️ <b>AJUDA E INSTRUÇÕES DE USO</b>\n\n"
        "<b>📋 Verificar Todas:</b> Consulta o status de todas as regulações que você cadastrou.\n"
        "<b>🔍 Verificar Específico:</b> Permite selecionar ou digitar o ID de uma regulação para verificar individualmente.\n"
        "<b>➕ Cadastrar Nova:</b> Cadastra uma nova regulação para monitoramento contínuo.\n"
        "<b>✏️ Corrigir ID:</b> Altera informações de um cadastro existente.\n"
        "<b>🗑️ Excluir Regulação:</b> Remove uma regulação da sua lista de monitoramento.\n\n"
        f"{DISCLAIMER_TEXTO}\n\n"
        "<i>Se precisar cancelar qualquer operação, clique em '🚫 Cancelar Operação' ou digite /cancelar.</i>"
    )
    await update.message.reply_text(mensagem, parse_mode="HTML", reply_markup=TECLADO_MENU)

async def cancelar_operacao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ Operação cancelada com sucesso.", reply_markup=TECLADO_MENU)
    return ConversationHandler.END

async def comando_verificar_todas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    regulacoes = buscar_regulacoes_por_usuario(user_id)
    if hasattr(regulacoes, "__await__"): regulacoes = await regulacoes

    if not regulacoes:
        await update.message.reply_text(
            "ℹ️ <b>Você não possui nenhuma regulação cadastrada.</b>\nUtilize a opção <b>➕ Cadastrar Nova</b> para cadastrar.",
            parse_mode="HTML", reply_markup=TECLADO_MENU
        )
        return

    msg_inicial = await update.message.reply_text(
        f"🔄 Consultando <b>{len(regulacoes)}</b> regulação(ões) na FMS... Por favor, aguarde.",
        parse_mode="HTML"
    )

    for reg in regulacoes:
        num_reg, _, _ = _extrair_id_e_nome(reg)
        try:
            resultado = await consultar_status_fms(num_reg)
        except Exception as e:
            logger.error(f"Erro FMS {num_reg}: {e}")
            resultado = {"sucesso": False}

        msg_html = _montar_msg_html(num_reg, resultado, reg)
        await update.message.reply_text(msg_html, parse_mode="HTML")

    try: await msg_inicial.delete()
    except Exception: pass

    await update.message.reply_text("✅ Consulta concluída!", reply_markup=TECLADO_MENU)

async def iniciar_verificar_especifico(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        user_id = update.effective_user.id
        regulacoes = buscar_regulacoes_por_usuario(user_id)
        if hasattr(regulacoes, "__await__"): regulacoes = await regulacoes

        if not regulacoes:
            msg_sem_dados = "⚠️ Nenhuma regulação cadastrada encontrada para o seu usuário."
            if update.message: 
                await update.message.reply_text(msg_sem_dados, reply_markup=TECLADO_MENU)
            elif update.callback_query: 
                await update.callback_query.message.reply_text(msg_sem_dados, reply_markup=TECLADO_MENU)
            return ConversationHandler.END

        teclado_botoes = []
        for reg in regulacoes:
            num_reg, nome_bruto, cbo = _extrair_id_e_nome(reg)
            
            cbo_str = f" ({cbo.strip().upper()})" if cbo and str(cbo).strip().upper() not in ["NONE", "N/A", ""] else ""
            rotulo_botao = f"📄 {num_reg} - {mascarar_nome(nome_bruto)}{cbo_str}"

            teclado_botoes.append([InlineKeyboardButton(rotulo_botao, callback_data=f"ver_esp_{num_reg}")])

        teclado_botoes.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_ver_esp")])
        reply_markup = InlineKeyboardMarkup(teclado_botoes)

        msg = "🔍 <b>Selecione qual regulação deseja verificar:</b>\n<i>Ou se preferir, digite o número do ID da regulação abaixo:</i>"
        if update.message: 
            await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode="HTML")
        elif update.callback_query: 
            await update.callback_query.message.reply_text(msg, reply_markup=reply_markup, parse_mode="HTML")

        return CONSULTAR_ID
    except Exception as e:
        logger.error(f"Erro em iniciar_verificar_especifico: {e}")
        return ConversationHandler.END

async def processar_verificar_especifico(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        num_reg = None

        if query:
            await query.answer()
            data = query.data

            if data == "cancelar_ver_esp":
                await query.edit_message_text("❌ Consulta cancelada.")
                await query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)
                context.user_data.clear()
                return ConversationHandler.END

            if data.startswith("ver_esp_"):
                num_reg = data.replace("ver_esp_", "").strip()

        elif update.message and update.message.text:
            if await verificar_se_e_menu_e_executar(update, context):
                return ConversationHandler.END
            num_reg = re.sub(r"\D", "", update.message.text.strip())

        if not num_reg:
            msg_erro = "⚠️ Não foi possível identificar o ID da regulação. Digite apenas os números:"
            if query: 
                await query.edit_message_text(msg_erro)
            else: 
                await update.message.reply_text(msg_erro, reply_markup=TECLADO_CANCELAR)
            return CONSULTAR_ID

        # 1. Atualiza visualmente informando o início da consulta
        msg_espera = f"⌛ <b>Consultando a regulação</b> <code>{escape(num_reg)}</code> na FMS... Por favor, aguarde."
        if query: 
            await query.edit_message_text(msg_espera, parse_mode="HTML")
        else: 
            msg_status = await update.message.reply_text(msg_espera, parse_mode="HTML")

        # 2. Realiza as buscas
        reg_db = await _buscar_regulacao_por_id_reg(num_reg)
        try: 
            resultado = await consultar_status_fms(num_reg)
        except Exception as e: 
            logger.error(f"Erro na consulta FMS: {e}")
            resultado = {"sucesso": False}

        # 3. Formata a mensagem de resposta
        msg_html = _montar_msg_html(num_reg, resultado, reg_db)

        # 4. Atualiza diretamente a mensagem onde o botão foi clicado
        if query:
            await query.edit_message_text(msg_html, parse_mode="HTML")
            await query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)
        else:
            try: 
                await msg_status.delete()
            except Exception: 
                pass
            await update.message.reply_text(msg_html, parse_mode="HTML", reply_markup=TECLADO_MENU)

        context.user_data.clear()
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Erro em processar_verificar_especifico: {e}")
        context.user_data.clear()
        return ConversationHandler.END
