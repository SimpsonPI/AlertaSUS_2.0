import logging
import asyncio
from html import escape
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import Forbidden, TelegramError
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes
)

from config import TELEGRAM_BOT_TOKEN
from database import (
    supabase,
    buscar_todas_regulacoes_ativas,
    atualizar_campo_regulacao,
    desativar_regulacoes_por_chat_id,
    ativar_ou_atualizar_assinatura  # <--- Adicionado aqui!
)

try:
    from scraper import consultar_status_fms, montar_mensagem_regulacao
except ImportError:
    async def consultar_status_fms(num_reg):
        return None
    def montar_mensagem_regulacao(*args, **kwargs):
        return ""

# 🔗 Link oficial do Telegra.ph com o Termo e Política de Privacidade
URL_TERMO_LGPD = "https://telegra.ph/DECLARA%C3%87%C3%83O-DE-INDEPEND%C3%8ANCIA-08-13"

VARREDURA_INTERVALO_MINUTOS = 120

logger = logging.getLogger(__name__)

from handlers_consultas import (
    start as start_consulta,
    comando_ajuda,
    comando_verificar_todas,
    iniciar_verificar_especifico,
    processar_verificar_especifico,
    cancelar_operacao
)
from handlers_cadastro import (
    iniciar_cadastro_manual,
    receber_sus,
    receber_nome,
    receber_celular,
    receber_nascimento,
    receber_regulacao,
    receber_cbo,
    receber_procedimento,
    finalizar_cadastro
)
from handlers_gestao import (
    iniciar_corrigir,
    selecionar_regulacao_callback,
    selecionar_campo_callback,
    salvar_novo_valor,
    iniciar_excluir,
    selecionar_regulacao_excluir_callback,
    confirmar_exclusao_callback
)
from utils import (
    CONSULTAR_ID,
    SELECIONAR_REGULACAO,
    SELECIONAR_CAMPO,
    AGUARDAR_NOVO_VALOR,
    SELECIONAR_REGULACAO_EXCLUIR,
    CONFIRMAR_EXCLUSAO,
    ETAPA_SUS, ETAPA_NOME, ETAPA_CELULAR, ETAPA_NASCIMENTO,
    ETAPA_REGULACAO, ETAPA_CBO, ETAPA_PROCEDIMENTO, ETAPA_LGPD
)


# --- MENU INTERATIVO DE BOTÕES NO CHAT (INLINE KEYBOARD) ---
def obter_menu_principal():
    """Gera o teclado interativo com as opções do menu principal."""
    keyboard = [
        [
            InlineKeyboardButton("🔍 Verificar Todos", callback_data="verificar_todos"),
            InlineKeyboardButton("🎯 Verificar Específico", callback_data="verificar_especifico")
        ],
        [
            InlineKeyboardButton("➕ Cadastrar Nova", callback_data="cadastrar_nova"),
            InlineKeyboardButton("✏️ Corrigir", callback_data="corrigir")
        ],
        [
            InlineKeyboardButton("💳 Planos", callback_data="planos"),
            InlineKeyboardButton("🗑️ Excluir", callback_data="excluir")
        ],
        [
            InlineKeyboardButton("🔒 Privacidade", callback_data="privacidade"),
            InlineKeyboardButton("❓ Ajuda", callback_data="ajuda")
        ],
        [
            InlineKeyboardButton("🚀 Iniciar / Menu Principal", callback_data="iniciar")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


# --- HANDLER DO COMANDO /START E /INICIAR ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler principal do /start ou /iniciar (exibe o menu interativo)."""
    user = update.effective_user
    nome = user.first_name or "Usuário"

    mensagem = (
        f"👋 Olá, <b>{nome}</b>! Bem-vindo ao <b>AlertaSUS 2.0</b>.\n\n"
        "Selecione uma das opções abaixo para gerenciar ou consultar suas regulações no SUS:"
    )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            mensagem, 
            parse_mode="HTML", 
            reply_markup=obter_menu_principal()
        )
    else:
        await update.message.reply_text(
            mensagem, 
            parse_mode="HTML", 
            reply_markup=obter_menu_principal()
        )


from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import supabase

# --- TECLADO, COMANDO E DETALHES DE PLANOS ---

async def obter_menu_planos(user_id: int) -> InlineKeyboardMarkup:
    """Gera os botões interativos verificando se o usuário já utilizou a degustação."""
    ja_usou_degustacao = False

    try:
        # Consulta o banco para verificar se já existe registro de degustação ou plano ativo para o chat_id
        res = supabase.table("assinaturas").select("tipo_plano").eq("chat_id", str(user_id)).execute()
        if res.data:
            planos_registrados = [row.get("tipo_plano") for row in res.data]
            if "degustacao" in planos_registrados or any(p in planos_registrados for p in ["pro_semestral", "pro_anual", "pro_mensal"]):
                ja_usou_degustacao = True
    except Exception as e:
        print(f"Erro ao verificar degustação no Supabase: {e}")

    keyboard = []

    # Se o usuário NÃO usou a degustação, inclui o botão gratuito
    if not ja_usou_degustacao:
        keyboard.append([
            InlineKeyboardButton("🎁 Plano Degustação", callback_data="plano_degustacao"),
            InlineKeyboardButton("⭐ Plano Semestral", callback_data="plano_semestral")
        ])
        keyboard.append([
            InlineKeyboardButton("🚀 Plano Anual", callback_data="plano_anual")
        ])
    else:
        # Exibe apenas os planos pagos se a degustação já tiver sido ativada
        keyboard.append([
            InlineKeyboardButton("⭐ Plano Semestral", callback_data="plano_semestral"),
            InlineKeyboardButton("🚀 Plano Anual", callback_data="plano_anual")
        ])

    keyboard.append([
        InlineKeyboardButton("⬅️ Voltar ao Menu Principal", callback_data="iniciar")
    ])

    return InlineKeyboardMarkup(keyboard)

async def comando_planos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe o menu de seleção dos planos cadastrados."""
    user_id = update.effective_user.id
    teclado = await obter_menu_planos(user_id)

    texto = (
        "💳 <b>Planos e Assinaturas — AlertaSUS</b>\n\n"
        "Acompanhe suas consultas e exames sem preocupações. Escolha o plano ideal "
        "para você e receba notificações instantâneas no seu Telegram assim que sua regulação andar!\n\n"
        "<i>Selecione uma das opções abaixo para ver mais detalhes:</i>"
    )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            texto,
            parse_mode="HTML",
            reply_markup=teclado
        )
    else:
        await update.message.reply_text(
            texto,
            parse_mode="HTML",
            reply_markup=teclado
        )

async def detalhar_plano(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ativa a degustação gratuitamente ou exibe opções de pagamento dos planos pagos."""
    query = update.callback_query
    
    try:
        await query.answer()
    except Exception:
        pass

    data = query.data
    telegram_id = query.from_user.id

    # 1. PLANO DEGUSTAÇÃO: Registra no banco e confirma diretamente
    if data == "plano_degustacao":
        try:
            supabase.table("assinaturas").upsert({
                "chat_id": str(telegram_id),
                "tipo_plano": "degustacao",
                "status": "ativo"
            }, on_conflict="chat_id").execute()
            print(f"✅ Degustação ativada para chat_id: {telegram_id}")
        except Exception as err:
            print(f"⚠️ Erro/Aviso ao salvar no Supabase: {err}")

        texto = (
            "🎁 <b>Plano Degustação Ativado!</b>\n\n"
            "Seu período de teste gratuito de 7 dias já está funcionando.\n\n"
            "• <b>Status:</b> Ativo\n"
            "• <b>Capacidade:</b> Até 2 regulações cadastradas\n"
            "• <b>Alertas:</b> Notificações diretas no Telegram\n\n"
            "Aproveite os recursos da plataforma!"
        )
        
        # Botões normais de callback (sem URL externa)
        keyboard_botoes = [
            [InlineKeyboardButton("⚡ Ver Planos Pro", callback_data="planos")],
            [InlineKeyboardButton("🏠 Menu Principal", callback_data="iniciar")]
        ]

    # 2. PLANO SEMESTRAL
    elif data == "plano_semestral":
        texto = (
            "⭐ <b>Plano Semestral</b>\n\n"
            "• <b>Monitoramento Contínuo:</b> Notificações automáticas via Telegram.\n"
            "• <b>Capacidade:</b> Até 5 regulações cadastradas.\n\n"
            "<b>Valor:</b> R$ 9,99 / semestre"
        )
        keyboard_botoes = [
            [InlineKeyboardButton("💳 Pagar via Pix", callback_data="pix_pro_semestral")],
            [InlineKeyboardButton("⬅️ Voltar aos Planos", callback_data="planos")]
        ]

    # 3. PLANO ANUAL
    elif data == "plano_anual":
        texto = (
            "🚀 <b>Plano Anual</b>\n\n"
            "• <b>Monitoramento Contínuo:</b> Notificações automáticas por 12 meses.\n"
            "• <b>Capacidade Ampliada:</b> Até 9 regulações cadastradas.\n\n"
            "<b>Valor:</b> R$ 14,99 / ano"
        )
        keyboard_botoes = [
            [InlineKeyboardButton("💳 Pagar via Pix", callback_data="pix_pro_anual")],
            [InlineKeyboardButton("⬅️ Voltar aos Planos", callback_data="planos")]
        ]
    else:
        texto = "Opção inválida."
        keyboard_botoes = [[InlineKeyboardButton("⬅️ Voltar", callback_data="planos")]]

    # Atualiza a mensagem no chat com o resultado
    await query.edit_message_text(
        text=texto,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard_botoes)
    )

# ... (outras funções do seu handler.py)

async def comando_planos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe o menu principal de planos."""
    keyboard = [
        [InlineKeyboardButton("🎁 Plano Degustação (Grátis)", callback_data="plano_degustacao")],
        [InlineKeyboardButton("⭐ Plano Semestral", callback_data="plano_semestral")],
        [InlineKeyboardButton("🚀 Plano Anual", callback_data="plano_anual")],
        [InlineKeyboardButton("⬅️ Voltar ao Menu Principal", callback_data="iniciar")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    texto = (
        "💳 <b>Escolha o seu plano de monitoramento:</b>\n\n"
        "Selecione uma das opções abaixo para ver os detalhes e realizar a contratação:"
    )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            texto,
            parse_mode="HTML",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            texto,
            parse_mode="HTML",
            reply_markup=reply_markup
        )


async def detalhar_plano(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ativa a degustação gratuitamente no Supabase ou exibe opções de pagamento dos planos pagos."""
    query = update.callback_query
    
    try:
        await query.answer()
    except Exception:
        pass

    data = query.data
    telegram_id = query.from_user.id

    # 1. PLANO DEGUSTAÇÃO: Salva no Supabase e responde diretamente no chat (SEM LINK)
    if data == "plano_degustacao":
        try:
            supabase.table("assinaturas").upsert({
                "chat_id": str(telegram_id),
                "tipo_plano": "degustacao",
                "status": "ativo"
            }, on_conflict="chat_id").execute()
            print(f"✅ Degustação gravada no Supabase para o usuário: {telegram_id}")
        except Exception as err:
            print(f"❌ Erro ao gravar degustação no Supabase: {err}")

        texto = (
            "🎁 <b>Plano Degustação Ativado!</b>\n\n"
            "Seu período de teste gratuito de 7 dias já está funcionando.\n\n"
            "• <b>Status:</b> Ativo\n"
            "• <b>Capacidade:</b> Até 2 regulações cadastradas\n"
            "• <b>Alertas:</b> Notificações diretas no Telegram\n\n"
            "Aproveite os recursos da plataforma!"
        )
        
        keyboard_botoes = [
            [InlineKeyboardButton("⚡ Ver Planos Pro", callback_data="planos")],
            [InlineKeyboardButton("🏠 Menu Principal", callback_data="iniciar")]
        ]

    # 2. PLANO SEMESTRAL
    elif data == "plano_semestral":
        texto = (
            "⭐ <b>Plano Semestral</b>\n\n"
            "• <b>Monitoramento Contínuo:</b> Notificações automáticas via Telegram.\n"
            "• <b>Capacidade:</b> Até 5 regulações cadastradas.\n\n"
            "<b>Valor:</b> R$ 9,99 / semestre"
        )
        keyboard_botoes = [
            [InlineKeyboardButton("💳 Pagar via Pix", callback_data="pix_pro_semestral")],
            [InlineKeyboardButton("⬅️ Voltar aos Planos", callback_data="planos")]
        ]

    # 3. PLANO ANUAL
    elif data == "plano_anual":
        texto = (
            "🚀 <b>Plano Anual</b>\n\n"
            "• <b>Monitoramento Contínuo:</b> Notificações automáticas por 12 meses.\n"
            "• <b>Capacidade Ampliada:</b> Até 9 regulações cadastradas.\n\n"
            "<b>Valor:</b> R$ 14,99 / ano"
        )
        keyboard_botoes = [
            [InlineKeyboardButton("💳 Pagar via Pix", callback_data="pix_pro_anual")],
            [InlineKeyboardButton("⬅️ Voltar aos Planos", callback_data="planos")]
        ]
    else:
        texto = "Opção de plano não encontrada."
        keyboard_botoes = [[InlineKeyboardButton("⬅️ Voltar", callback_data="planos")]]

    # Atualiza a mensagem na tela do Telegram
    await query.edit_message_text(
        text=texto,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard_botoes)
    )


# --- COMANDO DE PRIVACIDADE ---
async def comando_privacidade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe o link direto para o Termo de Consentimento e Política de Privacidade."""
    keyboard = [[InlineKeyboardButton("📄 Consultar Termo e Política", url=URL_TERMO_LGPD)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    texto = (
        "📋 <b>Termo de Consentimento e Política de Privacidade</b>\n\n"
        "Você pode consultar nosso documento completo sempre que desejar pelo link abaixo:"
    )

    if update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(
                texto,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
        except Exception:
            await update.callback_query.message.reply_text(
                texto,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
    else:
        await update.message.reply_text(
            texto,
            parse_mode="HTML",
            reply_markup=reply_markup
        )


# --- VARREDURA AUTOMÁTICA DETALHADA ---
async def executar_varredura_automatica(context: ContextTypes.DEFAULT_TYPE):
    """Executa a verificação periódica e envia o relatório apenas se houver MUDANÇA REAL de status no Supabase."""
    logger.info("Iniciando varredura automática de rotina detalhada...")
    try:
        regulacoes = buscar_todas_regulacoes_ativas()
        if not regulacoes:
            logger.info("Nenhuma regulação ativa encontrada para monitorar.")
            return

        for reg in regulacoes:
            num_reg = reg.get("numero_reg") or reg.get("numero_regulacao") or reg.get("id_regulacao")
            chat_id = reg.get("chat_id") or reg.get("id_do_chat") or reg.get("telegram_id")
            status_antigo = reg.get("status_anterior") or reg.get("status_atual") or "PENDENTE"

            if not num_reg or not chat_id:
                continue

            try:
                resultado_fms = await consultar_status_fms(str(num_reg))
            except Exception as err_sc:
                logger.error(f"Erro ao consultar FMS para regulação {num_reg}: {err_sc}")
                resultado_fms = None

            if isinstance(resultado_fms, dict) and resultado_fms.get("sucesso"):
                status_novo = resultado_fms.get("situacao") or "Informada no portal"
            else:
                status_novo = None

            if status_novo and str(status_novo).strip().upper() != str(status_antigo).strip().upper():
                try:
                    if asyncio.iscoroutinefunction(atualizar_campo_regulacao):
                        await atualizar_campo_regulacao(num_reg, "status_anterior", status_novo)
                    else:
                        atualizar_campo_regulacao(num_reg, "status_anterior", status_novo)
                    logger.info(f"Status da regulação {num_reg} atualizado no Supabase para: {status_novo}")
                except Exception as err_upd:
                    logger.error(f"Erro ao atualizar status no Supabase: {err_upd}")

                nome_paciente = reg.get("nome_paciente") or "Não informado"
                cartao_sus = reg.get("numero_sus") or "Não informado"
                procedimento = reg.get("procedimento") or "Não informado"
                cbo = reg.get("cbo") or "Não informado"
                celular = reg.get("celular") or "Não informado"

                header_alerta = (
                    f"🚨 <b>ALERTA DE ATUALIZAÇÃO NO SUS</b> 🚨\n\n"
                    f"<b>ID da Regulação:</b> <code>{escape(str(num_reg))}</code>\n"
                    f"📌 <b>Status Anterior:</b> {escape(str(status_antigo))}\n"
                    f"📌 <b>Novo Status:</b> <b>{escape(str(status_novo))}</b>\n"
                    f"───────────────────────────\n"
                    f"📋 <b>FICHA CADASTRAL (SUPABASE)</b>\n"
                    f"👤 <b>Paciente:</b> {escape(str(nome_paciente))}\n"
                    f"💳 <b>Cartão SUS:</b> {escape(str(cartao_sus))}\n"
                    f"🩺 <b>Procedimento:</b> {escape(str(procedimento))}\n"
                    f"🏷️ <b>CBO:</b> {escape(str(cbo))}\n"
                    f"📱 <b>Celular:</b> {escape(str(celular))}\n"
                    f"───────────────────────────"
                )

                detalhes_fms = ""
                if isinstance(resultado_fms, dict) and resultado_fms.get("sucesso"):
                    detalhes_fms = "\n\n🏥 <b>SITUAÇÃO NO PORTAL FMS</b>\n"
                    
                    alerta_fms = resultado_fms.get("alerta_fms") or resultado_fms.get("alerta")
                    if alerta_fms:
                        detalhes_fms += f"⚠️ <b>AVISO DO PORTAL:</b>\n<i>{escape(str(alerta_fms))}</i>\n\n"

                    if resultado_fms.get("data_consulta"):
                        detalhes_fms += f"• <b>Data/Hora:</b> {escape(str(resultado_fms.get('data_consulta')))}\n"
                        detalhes_fms += f"• <b>Local:</b> {escape(str(resultado_fms.get('estabelecimento') or 'Não informado'))}\n"
                        detalhes_fms += f"• <b>Endereço:</b> {escape(str(resultado_fms.get('endereco') or 'Não informado'))}\n"
                    else:
                        posicao = resultado_fms.get("posicao_fila") or "Não informada"
                        previsao = resultado_fms.get("previsao_atendimento") or "Não informada"
                        detalhes_fms += f"• <b>Posição na Fila:</b> {escape(str(posicao))}\n"
                        detalhes_fms += f"• <b>Previsão de Atendimento:</b> {escape(str(previsao))}\n"

                msg_completa = header_alerta + detalhes_fms

                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=msg_completa,
                        parse_mode="HTML"
                    )
                    logger.info(f"Notificação de alteração enviada com sucesso para o chat_id {chat_id}.")
                except Forbidden:
                    logger.warning(f"🚫 O usuário do chat_id {chat_id} bloqueou o bot. Desativando monitoramento.")
                    desativar_regulacoes_por_chat_id(chat_id)
                except TelegramError as te:
                    logger.error(f"Erro Telegram ao enviar para chat_id {chat_id}: {te}")
                except Exception as e:
                    logger.error(f"Erro ao enviar notificação para {chat_id}: {e}")

            await asyncio.sleep(0.1)

    except Exception as e:
        logger.error(f"Erro durante a execução da varredura automática: {e}")


# --- ALIASES E MAPEAMENTOS DIRETO DO MENU ---
cancelar_corrigir = cancelar_operacao
cancelar_excluir = cancelar_operacao
cancelar_cadastro = cancelar_operacao

verificar_todos = comando_verificar_todas
verificar_especifico = iniciar_verificar_especifico
cadastrar_nova = iniciar_cadastro_manual
corrigir = iniciar_corrigir
planos = comando_planos
excluir = iniciar_excluir
privacidade = comando_privacidade
ajuda = comando_ajuda


# --- CONFIGURAÇÃO DO MENU DE COMANDOS DO BOT (MENU FLUTUANTE DO TELEGRAM) ---
async def configurar_menu_comandos(app):
    """Configura as opções no menu de comandos oficial do Telegram."""
    comandos = [
        BotCommand("iniciar", "🚀 Menu principal e boas-vindas"),
        BotCommand("verificar_todos", "🔍 Verificar todas as regulações"),
        BotCommand("verificar_especifico", "🎯 Verificar regulação específica"),
        BotCommand("cadastrar_nova", "➕ Cadastrar nova regulação"),
        BotCommand("corrigir", "✏️ Corrigir dados de regulação"),
        BotCommand("planos", "💳 Ver planos e assinaturas"),
        BotCommand("excluir", "🗑️ Excluir uma regulação"),
        BotCommand("privacidade", "🔒 Política de privacidade e LGPD"),
        BotCommand("ajuda", "❓ Central de ajuda e suporte")
    ]
    await app.bot.set_my_commands(comandos)


# --- CONVERSATION HANDLERS ---
conv_consulta_especifica = ConversationHandler(
    entry_points=[
        CommandHandler("consultar", iniciar_verificar_especifico),
        CommandHandler("verificar_especifico", iniciar_verificar_especifico),
        CallbackQueryHandler(iniciar_verificar_especifico, pattern="^verificar_especifico$")
    ],
    states={
        CONSULTAR_ID: [
            CallbackQueryHandler(processar_verificar_especifico),
            MessageHandler(filters.TEXT & ~filters.COMMAND, processar_verificar_especifico)
        ]
    },
    fallbacks=[CommandHandler("cancelar", cancelar_operacao)]
)

conv_cadastro = ConversationHandler(
    entry_points=[
        CommandHandler("cadastrar", iniciar_cadastro_manual),
        CommandHandler("cadastrar_nova", iniciar_cadastro_manual),
        CallbackQueryHandler(iniciar_cadastro_manual, pattern="^cadastrar_nova$")
    ],
    states={
        ETAPA_SUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_sus)],
        ETAPA_NOME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_nome)],
        ETAPA_CELULAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_celular)],
        ETAPA_NASCIMENTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_nascimento)],
        ETAPA_REGULACAO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_regulacao)],
        ETAPA_CBO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_cbo)],
        ETAPA_PROCEDIMENTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_procedimento)],
        ETAPA_LGPD: [CallbackQueryHandler(finalizar_cadastro)]
    },
    fallbacks=[
        CommandHandler("cancelar", cancelar_operacao),
        MessageHandler(filters.Regex("^🚫 Cancelar Operação$"), cancelar_operacao)
    ]
)

conv_corrigir = ConversationHandler(
    entry_points=[
        CommandHandler("corrigir", iniciar_corrigir),
        CallbackQueryHandler(iniciar_corrigir, pattern="^corrigir$")
    ],
    states={
        SELECIONAR_REGULACAO: [
            CallbackQueryHandler(selecionar_regulacao_callback, pattern="^(corr_reg_|cancelar_corr)")
        ],
        SELECIONAR_CAMPO: [
            CallbackQueryHandler(selecionar_campo_callback, pattern="^(form_edit_|form_salvar_|corr_campo_|cancelar_corr)")
        ],
        AGUARDAR_NOVO_VALOR: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, salvar_novo_valor)
        ]
    },
    fallbacks=[CommandHandler("cancelar", cancelar_operacao)]
)

conv_excluir = ConversationHandler(
    entry_points=[
        CommandHandler("excluir", iniciar_excluir),
        CallbackQueryHandler(iniciar_excluir, pattern="^excluir$")
    ],
    states={
        SELECIONAR_REGULACAO_EXCLUIR: [CallbackQueryHandler(selecionar_regulacao_excluir_callback, pattern="^(excl_reg_|cancelar_excl)")],
        CONFIRMAR_EXCLUSAO: [CallbackQueryHandler(confirmar_exclusao_callback, pattern="^(conf_excl_sim|cancelar_excl)")]
    },
    fallbacks=[CommandHandler("cancelar", cancelar_operacao)]
)


# --- PROCESSADOR DE CLIQUES DO MENU (TEXTO) ---
from utils import TECLADO_MENU

async def tratar_menu_interativo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Filtra e executa as ações selecionadas no teclado de texto."""
    texto = update.message.text
    
    if texto == "🔍 Verificar Todos":
        await comando_verificar_todas(update, context)
    elif texto == "🎯 Verificar Específico":
        await iniciar_verificar_especifico(update, context)
    elif texto == "➕ Cadastrar Nova":
        await iniciar_cadastro_manual(update, context)
    elif texto == "✏️ Corrigir":
        await iniciar_corrigir(update, context)
    elif texto == "💎 Planos":
        await comando_planos(update, context)
    elif texto == "🗑️ Excluir":
        await iniciar_excluir(update, context)
    elif texto == "🔒 Privacidade":
        await comando_privacidade(update, context)
    elif texto == "❓ Ajuda":
        await comando_ajuda(update, context)
    elif texto == "🚀 Iniciar / Menu Principal":
        await start(update, context)

# --- EXPORTAÇÃO DE SÍMBOLOS DO HANDLER ---
__all__ = [
    "CONSULTAR_ID", "SELECIONAR_REGULACAO", "SELECIONAR_CAMPO", "AGUARDAR_NOVO_VALOR",
    "SELECIONAR_REGULACAO_EXCLUIR", "CONFIRMAR_EXCLUSAO", "ETAPA_SUS", "ETAPA_NOME",
    "ETAPA_CELULAR", "ETAPA_NASCIMENTO", "ETAPA_REGULACAO", "ETAPA_CBO", "ETAPA_PROCEDIMENTO",
    "ETAPA_LGPD", "start", "comando_ajuda", "comando_privacidade", "comando_planos", "cancelar_operacao",
    "configurar_menu_comandos", "executar_varredura_automatica", "comando_verificar_todas",
    "iniciar_verificar_especifico", "processar_verificar_especifico", "iniciar_cadastro_manual",
    "receber_sus", "receber_nome", "receber_celular", "receber_nascimento", "receber_regulacao",
    "receber_cbo", "receber_procedimento", "finalizar_cadastro", "iniciar_corrigir",
    "selecionar_regulacao_callback", "selecionar_campo_callback", "salvar_novo_valor",
    "cancelar_corrigir", "iniciar_excluir", "selecionar_regulacao_excluir_callback",
    "confirmar_exclusao_callback", "cancelar_excluir",
    "conv_consulta_especifica", "conv_cadastro", "conv_corrigir", "conv_excluir",
    "tratar_menu_interativo", "obter_menu_principal", "obter_menu_planos", "detalhar_plano"
]