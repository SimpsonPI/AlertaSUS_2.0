import logging
import re
from html import escape
from datetime import datetime

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand
)
from telegram.ext import (
    ContextTypes,
    ConversationHandler
)

# Tenta importar do config, com fallback para padrão se não existir
try:
    from config import VARREDURA_INTERVALO_MINUTOS
except ImportError:
    VARREDURA_INTERVALO_MINUTOS = 30

# Importação do Banco de Dados com fallback de segurança
try:
    from database import (
        buscar_regulacoes_por_chat_id as buscar_regulacoes_por_usuario,
        salvar_regulacao,
        atualizar_campo_regulacao,
        excluir_regulacao_db,
        obter_regulacao_por_id,
        obter_regulacao_por_numero,
        registrar_consentimento_lgpd
    )
except ImportError:
    from database import *

# Busca flexível da função de varredura
try:
    from database import buscar_todas_regulacoes_ativas
except ImportError:
    try:
        from database import obter_todas_regulacoes as buscar_todas_regulacoes_ativas
    except ImportError:
        async def buscar_todas_regulacoes_ativas():
            return []

from scraper import consultar_status_fms

# Configuração de Logging Unificada
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --------------------------------------------------
# ESTADOS DAS CONVERSAÇÕES
# --------------------------------------------------

# Consulta Específica
CONSULTAR_ID = 1

# Correção
SELECIONAR_REGULACAO = 10
SELECIONAR_CAMPO = 11
AGUARDAR_NOVO_VALOR = 12

# Exclusão
SELECIONAR_REGULACAO_EXCLUIR = 20
CONFIRMAR_EXCLUSAO = 21

# Cadastro Manual
ETAPA_SUS = 30
ETAPA_NOME = 31
ETAPA_CELULAR = 32
ETAPA_NASCIMENTO = 33
ETAPA_REGULACAO = 34
ETAPA_CBO = 35
ETAPA_PROCEDIMENTO = 36
ETAPA_LGPD = 37

# --------------------------------------------------
# TECLADOS
# --------------------------------------------------

TECLADO_MENU = ReplyKeyboardMarkup(
    [
        ["📋 Verificar Todas", "🔍 Verificar Específico"],
        ["➕ Cadastrar Nova", "✏️ Corrigir ID"],
        ["🗑️ Excluir Regulação", "ℹ️ Ajuda"]
    ],
    resize_keyboard=True
)

TECLADO_CANCELAR = ReplyKeyboardMarkup(
    [["🚫 Cancelar Operação"]],
    resize_keyboard=True
)

# Textos dos botões do menu principal + botão de cancelar.
# Usados para detectar quando o usuário aperta um botão do menu
# enquanto está no meio de um formulário (ex: cadastro, correção).
BOTOES_MENU = {
    "📋 Verificar Todas",
    "🔍 Verificar Específico",
    "➕ Cadastrar Nova",
    "✏️ Corrigir ID",
    "🗑️ Excluir Regulação",
    "ℹ️ Ajuda",
    "🚫 Cancelar Operação",
}

# --------------------------------------------------
# FUNÇÕES AUXILIARES E FORMATADORES
# --------------------------------------------------

async def verificar_se_e_menu_e_executar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Verifica se o texto recebido é um dos botões do menu principal
    (ou o botão de cancelar), em vez de uma resposta válida do formulário.

    Isto evita o bug em que, ao apertar um botão do menu no meio de uma
    conversa (ex: cadastro), o texto do botão era tratado como resposta
    inválida do campo atual, gerando um loop de erro sem saída.

    Se o texto corresponder a um botão do menu: cancela a operação atual
    e mostra o menu principal novamente, retornando True.
    Caso contrário, retorna False e o fluxo normal do formulário continua.
    """
    texto = update.message.text.strip() if update.message and update.message.text else ""

    if texto in BOTOES_MENU:
        await cancelar_operacao(update, context)
        return True

    return False

def _extrair_id_e_nome(reg: dict):
    """
    Extrai o número da regulação e o nome do paciente.
    ALINHADO COM COLUNAS DO SUPABASE:
    - numero_regulacao (ID da regulação)
    - nome_paciente (Nome do paciente)
    """
    # Tenta múltiplos nomes de coluna para o ID/número de regulação
    num_id = (
        reg.get("numero_regulacao") or 
        reg.get("numero_reg") or 
        reg.get("num_regulacao") or 
        reg.get("id_regulacao") or 
        reg.get("id") or
        "N/A"
    )
    
    # Tenta múltiplos nomes de coluna para o nome do paciente
    nome = (
        reg.get("nome_paciente") or 
        reg.get("nome") or 
        reg.get("paciente") or 
        "Paciente não informado"
    )
    
    return str(num_id), str(nome)


def _extrair_campos_completos(reg: dict):
    """
    Extrai todos os campos de uma regulação com fallbacks.
    Alinhado com estrutura de colunas do Supabase.
    """
    return {
        "id": reg.get("id") or reg.get("id_regulacao"),
        "numero_regulacao": reg.get("numero_regulacao") or reg.get("numero_reg"),
        "cartao_sus": reg.get("cartao_sus") or reg.get("numero_sus"),
        "nome_paciente": reg.get("nome_paciente") or reg.get("nome"),
        "celular": reg.get("celular") or reg.get("telefone"),
        "data_nascimento": reg.get("data_nascimento") or reg.get("nascimento"),
        "cbo": reg.get("cbo"),
        "procedimento": reg.get("procedimento"),
        "status_atual": reg.get("status_atual") or reg.get("status"),
        "especialidade": reg.get("especialidade") or reg.get("especialidade_procedimento"),
        "posicao_fila": reg.get("posicao_fila") or reg.get("posicao"),
        "data_regulacao": reg.get("data_regulacao") or reg.get("data_criacao"),
    }


async def configurar_menu_comandos(app):
    """Configura o menu de comandos do Telegram (botão azul)."""
    comandos = [
        BotCommand("start", "Inicia o bot e exibe o menu principal"),
        BotCommand("verificar", "Verifica o status de todas as suas regulações"),
        BotCommand("consultar", "Consulta o status de uma regulação específica"),
        BotCommand("cadastrar", "Cadastra uma nova regulação"),
        BotCommand("corrigir", "Corrige dados de uma regulação cadastrada"),
        BotCommand("excluir", "Exclui uma regulação cadastrada"),
        BotCommand("ajuda", "Exibe as instruções de uso do sistema")
    ]
    await app.bot.set_my_commands(comandos)

# --------------------------------------------------
# HANDLERS BASE E COMANDOS DIRECTOS
# --------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o bot e apresenta o menu principal."""
    user = update.effective_user
    context.user_data.clear()
    
    mensagem = (
        f"Olá, <b>{escape(user.first_name)}</b>! 👋\n\n"
        f"Bem-vindo ao <b>AlertaSUS 2.0</b>.\n"
        f"Eu ajudo você a acompanhar o status de suas regulações na FMS Piauí em tempo real.\n\n"
        f"Escolha uma opção no menu abaixo para começar:"
    )
    await update.message.reply_text(mensagem, parse_mode="HTML", reply_markup=TECLADO_MENU)

async def comando_ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe o guia de ajuda e uso do sistema."""
    mensagem = (
        "ℹ️ <b>AJUDA E INSTRUÇÕES DE USO</b>\n\n"
        "<b>📋 Verificar Todas:</b> Consulta o status de todas as regulações que você cadastrou.\n"
        "<b>🔍 Verificar Específico:</b> Permite selecionar ou digitar o ID de uma regulação para verificar individualmente.\n"
        "<b>➕ Cadastrar Nova:</b> Cadastra uma nova regulação para monitoramento contínuo.\n"
        "<b>✏️ Corrigir ID:</b> Altera informações de um cadastro existente.\n"
        "<b>🗑️ Excluir Regulação:</b> Remove uma regulação da sua lista de monitoramento.\n\n"
        "<i>Se precisar cancelar qualquer operação, clique em '🚫 Cancelar Operação' ou digite /cancelar.</i>"
    )
    await update.message.reply_text(mensagem, parse_mode="HTML", reply_markup=TECLADO_MENU)

async def cancelar_operacao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancela a operação atual e retorna ao menu principal."""
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Operação cancelada com sucesso.",
        reply_markup=TECLADO_MENU
    )
    return ConversationHandler.END

# --------------------------------------------------
# FLUXO DE CONSULTA (VERIFICAR TODAS / ESPECÍFICO)
# --------------------------------------------------

async def comando_verificar_todas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verifica todas as regulações cadastradas pelo usuário com isolamento de erros."""
    user_id = update.effective_user.id
    regulacoes = buscar_regulacoes_por_usuario(user_id)

    if not regulacoes:
        await update.message.reply_text(
            "ℹ️ <b>Você não possui nenhuma regulação cadastrada.</b>\n"
            "Utilize a opção <b>➕ Cadastrar Nova</b> para cadastrar.",
            parse_mode="HTML",
            reply_markup=TECLADO_MENU
        )
        return

    msg_inicial = await update.message.reply_text(
        f"🔄 Consultando <b>{len(regulacoes)}</b> regulação(ões) na FMS... Por favor, aguarde.",
        parse_mode="HTML"
    )

    resultados = []
    for reg in regulacoes:
        try:
            num_reg, nome = _extrair_id_e_nome(reg)
            campos = _extrair_campos_completos(reg)
            
            resultado = await consultar_status_fms(num_reg)
            resultados.append({
                "numero": num_reg,
                "nome": nome,
                "campos": campos,
                "resultado": resultado
            })
        except Exception as e:
            logger.error(f"Erro ao consultar regulação: {e}")
            continue

    if not resultados:
        await msg_inicial.edit_text("❌ Erro ao consultar as regulações. Tente novamente mais tarde.")
        return

    # Monta mensagem com todos os resultados
    msg_resposta = "📋 <b>STATUS DE TODAS AS SUAS REGULAÇÕES:</b>\n\n"
    
    for item in resultados:
        campos = item["campos"]
        resultado = item["resultado"]
        
        msg_resposta += (
            f"<b>Regulação: {item['numero']}</b>\n"
            f"👤 Paciente: {item['nome']}\n"
            f"🆔 Cartão SUS: {campos['cartao_sus'] or 'N/A'}\n"
            f"📊 Status: {campos['status_atual'] or resultado.get('status', 'N/A')}\n"
            f"📍 Fila: {campos['posicao_fila'] or 'N/A'}\n"
            f"🏥 Especialidade: {campos['especialidade'] or 'N/A'}\n\n"
        )

    await msg_inicial.edit_text(msg_resposta, parse_mode="HTML")
    await update.message.reply_text("Escolha uma opção:", reply_markup=TECLADO_MENU)


async def iniciar_verificar_especifico(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Inicia a consulta específica de uma regulação."""
    user_id = update.effective_user.id
    regulacoes = buscar_regulacoes_por_usuario(user_id)

    if not regulacoes:
        await update.message.reply_text(
            "⚠️ Você não possui nenhuma regulação cadastrada.",
            reply_markup=TECLADO_MENU
        )
        return ConversationHandler.END

    teclado = []
    for reg in regulacoes:
        num, nome = _extrair_id_e_nome(reg)
        teclado.append([InlineKeyboardButton(f"🔍 {num} - {nome}", callback_data=f"ver_esp_{num}")])
    teclado.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_ver_esp")])

    await update.message.reply_text(
        "🔍 <b>Selecione qual regulação deseja verificar:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(teclado)
    )
    return CONSULTAR_ID


async def processar_verificar_especifico(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Processa a verificação específica de uma regulação."""
    query = update.callback_query
    user_id = update.effective_user.id

    if query:
        await query.answer()
        if query.data == "cancelar_ver_esp":
            await query.edit_message_text("❌ Consulta cancelada.")
            await query.message.reply_text("Menu:", reply_markup=TECLADO_MENU)
            return ConversationHandler.END

        num_regulacao = query.data.replace("ver_esp_", "")
    else:
        if await verificar_se_e_menu_e_executar(update, context):
            return ConversationHandler.END
        num_regulacao = update.message.text.strip()

    try:
        resultado = await consultar_status_fms(num_regulacao)
        
        if resultado.get("sucesso"):
            msg = (
                f"<b>STATUS DA REGULAÇÃO</b>\n"
                f"ID Regulação: {num_regulacao}\n"
                f"Cartão SUS: {resultado.get('cartao_sus', 'N/A')}\n"
                f"Paciente: {resultado.get('nome_paciente', 'N/A')}\n"
                f"Especialidade/Procedimento: {resultado.get('especialidade_procedimento', 'N/A')}\n"
                f"Status: {resultado.get('status', 'N/A')}\n"
                f"Posição na Fila: {resultado.get('posicao_fila', 'N/A')}\n"
            )
        else:
            msg = f"❌ Regulação {num_regulacao} não encontrada no sistema FMS."

        if query:
            await query.edit_message_text(msg, parse_mode="HTML")
        else:
            await update.message.reply_text(msg, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Erro ao consultar regulação específica: {e}")
        if query:
            await query.edit_message_text("❌ Erro ao consultar. Tente novamente.")
        else:
            await update.message.reply_text("❌ Erro ao consultar. Tente novamente.")

    await update.message.reply_text("Escolha uma opção:", reply_markup=TECLADO_MENU)
    context.user_data.clear()
    return ConversationHandler.END


# --------------------------------------------------
# FLUXO DE CADASTRO
# --------------------------------------------------

async def iniciar_cadastro_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Inicia o fluxo de cadastro manual de regulação."""
    context.user_data.clear()
    await update.message.reply_text(
        "📝 <b>CADASTRO DE NOVA REGULAÇÃO</b>\n\n"
        "Digite o <b>número do Cartão SUS</b> do paciente (14 dígitos):",
        parse_mode="HTML",
        reply_markup=TECLADO_CANCELAR
    )
    return ETAPA_SUS


async def receber_sus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Recebe e valida o número do Cartão SUS."""
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    sus = update.message.text.strip()
    
    if not re.match(r'^\d{14}$', sus):
        await update.message.reply_text(
            "❌ Cartão SUS deve ter 14 dígitos. Tente novamente:",
            reply_markup=TECLADO_CANCELAR
        )
        return ETAPA_SUS
    
    context.user_data["sus"] = sus
    await update.message.reply_text(
        "✅ Cartão SUS registrado.\n\n"
        "Digite o <b>nome do paciente</b>:",
        parse_mode="HTML",
        reply_markup=TECLADO_CANCELAR
    )
    return ETAPA_NOME


async def receber_nome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Recebe o nome do paciente."""
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    context.user_data["nome"] = update.message.text.strip()
    await update.message.reply_text(
        "✅ Nome registrado.\n\n"
        "Digite o <b>celular</b> (com DDD, ex: 86999999999):",
        parse_mode="HTML",
        reply_markup=TECLADO_CANCELAR
    )
    return ETAPA_CELULAR


async def receber_celular(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Recebe o celular do paciente."""
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    context.user_data["celular"] = update.message.text.strip()
    await update.message.reply_text(
        "✅ Celular registrado.\n\n"
        "Digite a <b>data de nascimento</b> (formato: DD/MM/YYYY):",
        parse_mode="HTML",
        reply_markup=TECLADO_CANCELAR
    )
    return ETAPA_NASCIMENTO


async def receber_nascimento(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Recebe a data de nascimento."""
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    nascimento = update.message.text.strip()
    
    if not re.match(r'^\d{2}/\d{2}/\d{4}$', nascimento):
        await update.message.reply_text(
            "❌ Formato inválido. Use DD/MM/YYYY:",
            reply_markup=TECLADO_CANCELAR
        )
        return ETAPA_NASCIMENTO
    
    context.user_data["nascimento"] = nascimento
    await update.message.reply_text(
        "✅ Data de nascimento registrada.\n\n"
        "Digite o <b>número da regulação</b>:",
        parse_mode="HTML",
        reply_markup=TECLADO_CANCELAR
    )
    return ETAPA_REGULACAO


async def receber_regulacao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Recebe o número da regulação."""
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    context.user_data["numero_regulacao"] = update.message.text.strip()
    await update.message.reply_text(
        "✅ Número da regulação registrado.\n\n"
        "Digite o <b>CBO</b> (deixe em branco se não souber):",
        parse_mode="HTML",
        reply_markup=TECLADO_CANCELAR
    )
    return ETAPA_CBO


async def receber_cbo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Recebe o CBO."""
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    context.user_data["cbo"] = update.message.text.strip() or None
    await update.message.reply_text(
        "✅ CBO registrado.\n\n"
        "Digite o <b>procedimento</b> solicitado:",
        parse_mode="HTML",
        reply_markup=TECLADO_CANCELAR
    )
    return ETAPA_PROCEDIMENTO


async def receber_procedimento(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Recebe o procedimento."""
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    context.user_data["procedimento"] = update.message.text.strip()
    
    # Exibe confirmação LGPD
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Aceitar", callback_data="aceitar_lgpd")],
        [InlineKeyboardButton("❌ Recusar", callback_data="cancelar_cadastro")]
    ])
    
    await update.message.reply_text(
        "<b>CONFORMIDADE COM LGPD</b>\n\n"
        "Você autoriza o AlertaSUS 2.0 a coletar e armazenar seus dados pessoais "
        "para acompanhar regulações na FMS Piauí?",
        parse_mode="HTML",
        reply_markup=keyboard
    )
    return ETAPA_LGPD


async def finalizar_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Finaliza o cadastro."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancelar_cadastro":
        await query.edit_message_text("❌ Cadastro cancelado.")
        await query.message.reply_text("Menu:", reply_markup=TECLADO_MENU)
        context.user_data.clear()
        return ConversationHandler.END
    
    user_id = update.effective_user.id
    dados = context.user_data

    dados_salvar = {
        "telegram_id": user_id,
        "cartao_sus": dados.get("sus"),
        "nome_paciente": dados.get("nome"),
        "celular": dados.get("celular"),
        "data_nascimento": dados.get("nascimento"),
        "numero_regulacao": dados.get("numero_regulacao"),
        "cbo": dados.get("cbo"),
        "procedimento": dados.get("procedimento")
    }

    sucesso = await salvar_regulacao(dados_salvar)
    await registrar_consentimento_lgpd(user_id, aceito=True)

    if sucesso:
        await query.edit_message_text("✅ <b>Regulação cadastrada com sucesso!</b>\nEla será monitorada automaticamente.", parse_mode="HTML")
    else:
        await query.edit_message_text("❌ Erro ao salvar. Tente novamente.", parse_mode="HTML")

    await query.message.reply_text("Escolha uma opção:", reply_markup=TECLADO_MENU)
    context.user_data.clear()
    return ConversationHandler.END

# --------------------------------------------------
# FLUXO DE CORREÇÃO
# --------------------------------------------------

async def iniciar_corrigir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    regulacoes = buscar_regulacoes_por_usuario(user_id)

    if not regulacoes:
        await update.message.reply_text("⚠️ Você não possui regulações cadastradas para corrigir.", reply_markup=TECLADO_MENU)
        return ConversationHandler.END

    teclado = []
    for r in regulacoes:
        num, nome = _extrair_id_e_nome(r)
        db_id = r.get("id") or r.get("id_regulacao") or num
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

    reg_id = query.data.replace("corr_reg_", "")
    context.user_data["corr_reg_id"] = reg_id

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("Cartão SUS", callback_data="corr_campo_cartao_sus"), InlineKeyboardButton("Nome", callback_data="corr_campo_nome_paciente")],
        [InlineKeyboardButton("Celular", callback_data="corr_campo_celular"), InlineKeyboardButton("Nascimento", callback_data="corr_campo_data_nascimento")],
        [InlineKeyboardButton("Nº Regulação", callback_data="corr_campo_numero_regulacao"), InlineKeyboardButton("Procedimento", callback_data="corr_campo_procedimento")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_corr")]
    ])

    await query.edit_message_text("Selecione qual campo você deseja alterar:", reply_markup=teclado)
    return SELECIONAR_CAMPO

async def selecionar_campo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancelar_corr":
        await query.edit_message_text("❌ Operação de correção cancelada.")
        await query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)
        return ConversationHandler.END

    campo = query.data.replace("corr_campo_", "")
    context.user_data["corr_campo"] = campo

    await query.edit_message_text(f"Digite o novo valor para <b>{campo.replace('_', ' ').title()}</b>:", parse_mode="HTML")
    return AGUARDAR_NOVO_VALOR

async def salvar_novo_valor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await verificar_se_e_menu_e_executar(update, context):
        return ConversationHandler.END

    novo_valor = update.message.text.strip()
    reg_id = context.user_data.get("corr_reg_id")
    campo = context.user_data.get("corr_campo")

    sucesso = await atualizar_campo_regulacao(reg_id, campo, novo_valor)

    if sucesso:
        await update.message.reply_text("✅ Campo atualizado com sucesso!", reply_markup=TECLADO_MENU)
    else:
        await update.message.reply_text("❌ Falha ao atualizar o registro no banco de dados.", reply_markup=TECLADO_MENU)

    context.user_data.clear()
    return ConversationHandler.END

async def cancelar_corrigir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await cancelar_operacao(update, context)

# --------------------------------------------------
# FLUXO DE EXCLUSÃO
# --------------------------------------------------

async def iniciar_excluir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    regulacoes = buscar_regulacoes_por_usuario(user_id)

    if not regulacoes:
        await update.message.reply_text("⚠️ Você não possui nenhuma regulação cadastrada para excluir.", reply_markup=TECLADO_MENU)
        return ConversationHandler.END

    teclado = []
    for r in regulacoes:
        num, nome = _extrair_id_e_nome(r)
        db_id = r.get("id") or r.get("id_regulacao") or num
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

    reg_id = query.data.replace("excl_reg_", "")
    context.user_data["excl_reg_id"] = reg_id

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
        sucesso = await excluir_regulacao_db(reg_id)

        if sucesso:
            await query.edit_message_text("✅ Regulação excluída com sucesso!")
        else:
            await query.edit_message_text("❌ Ocorreu um erro ao tentar excluir a regulação.")
    else:
        await query.edit_message_text("❌ Exclusão cancelada.")

    await query.message.reply_text("Menu principal:", reply_markup=TECLADO_MENU)
    context.user_data.clear()
    return ConversationHandler.END

async def cancelar_excluir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await cancelar_operacao(update, context)

# --------------------------------------------------
# VARREDURA AUTOMÁTICA EM BACKGROUND
# --------------------------------------------------

async def executar_varredura_automatica(context: ContextTypes.DEFAULT_TYPE):
    """Executa a verificação periódica de todas as regulações cadastradas e notifica mudanças."""
    logger.info("🤖 Iniciando varredura automática de regulações...")
    regulacoes = await buscar_todas_regulacoes_ativas()

    for reg in regulacoes:
        try:
            num_reg, nome = _extrair_id_e_nome(reg)
            campos = _extrair_campos_completos(reg)
            telegram_id = reg.get("telegram_id")
            status_antigo = campos['status_atual']

            resultado = await consultar_status_fms(num_reg)

            if resultado.get("sucesso"):
                novo_status = resultado.get("status")
                if novo_status and novo_status != status_antigo:
                    reg_db_id = reg.get("id") or reg.get("id_regulacao")
                    if reg_db_id:
                        await atualizar_campo_regulacao(reg_db_id, "status_atual", novo_status)
                    
                    msg_notificacao = (
                        f"🔔 <b>MUDANÇA DE STATUS DETECTADA!</b>\n\n"
                        f"<b>Regulação:</b> {num_reg}\n"
                        f"<b>Paciente:</b> {nome}\n"
                        f"<b>Status Anterior:</b> {status_antigo}\n"
                        f"<b>Novo Status:</b> {novo_status}\n"
                        f"<b>Posição na Fila:</b> {resultado.get('posicao_fila', 'N/A')}"
                    )
                    try:
                        await context.bot.send_message(chat_id=telegram_id, text=msg_notificacao, parse_mode="HTML")
                    except Exception as e:
                        logger.error(f"Erro ao enviar notificação para {telegram_id}: {e}")
        except Exception as e:
            logger.error(f"Erro na varredura automática: {e}")
