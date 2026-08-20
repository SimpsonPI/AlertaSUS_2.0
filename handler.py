import asyncio
from html import escape
import logging
import warnings

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.warnings import PTBUserWarning

# Silencia os avisos de rastreamento do ConversationHandler
warnings.filterwarnings("ignore", category=PTBUserWarning)

from config import TELEGRAM_BOT_TOKEN
from database import (
    ativar_ou_atualizar_assinatura,
    atualizar_campo_regulacao,
    buscar_todas_regulacoes_ativas,
    desativar_regulacoes_por_chat_id,
    supabase,
)
from handler_cadastro import (
    iniciar_cadastro_manual,
    receber_cbo,
    receber_celular,
    receber_nascimento,
    receber_nome,
    receber_procedimento,
    receber_regulacao,
    receber_sus,
    finalizar_cadastro,  # <-- Adicione esta linha no bloco de importação
)

from handler_consultas import (
    cancelar_operacao,
    comando_ajuda,
    comando_verificar_todas,
    iniciar_verificar_especifico,
    processar_verificar_especifico,
)
from handler_gestao import (
    confirmar_exclusao_callback,
    iniciar_corrigir,
    iniciar_excluir,
    salvar_novo_valor,
    selecionar_campo_callback,
    selecionar_regulacao_callback,
    selecionar_regulacao_excluir_callback,
)
from utils import (
    AGUARDAR_NOVO_VALOR,
    CONFIRMAR_EXCLUSAO,
    CONSULTAR_ID,
    ETAPA_CBO,
    ETAPA_CELULAR,
    ETAPA_LGPD,
    ETAPA_NASCIMENTO,
    ETAPA_NOME,
    ETAPA_PROCEDIMENTO,
    ETAPA_REGULACAO,
    ETAPA_SUS,
    SELECIONAR_CAMPO,
    SELECIONAR_REGULACAO,
    SELECIONAR_REGULACAO_EXCLUIR,
)

try:
    from scraper import consultar_status_fms, montar_mensagem_regulacao
except ImportError:

    async def consultar_status_fms(num_reg):
        return None

    def montar_mensagem_regulacao(*args, **kwargs):
        return ""


URL_TERMO_LGPD = (
    "https://telegra.ph/DECLARA%C3%87%C3%83O-DE-INDEPEND%C3%8ANCIA-08-13"
)
VARREDURA_INTERVALO_MINUTOS = 120

logger = logging.getLogger(__name__)


# --- REMOÇÃO DO MENU FLUTUANTE ---
def obter_menu_principal():
    """Remove qualquer teclado persistente da tela do usuário."""
    return ReplyKeyboardRemove()


# --- HANDLER DO COMANDO /START E /INICIAR ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler principal do /start ou /iniciar."""
    user = update.effective_user
    nome = user.first_name or "Usuário"

    mensagem = (
        f"👋 Olá, <b>{nome}</b>! Bem-vindo ao <b>AlertaSUS 2.0</b>.\n\n"
        f"🆔 <b>Seu ID do Telegram:</b> <code>{user.id}</code>\n\n"
        "Acesse todas as opções e comandos diretamente pelo menu nativo do Telegram "
        "(botão <b>[/]</b> ao lado da barra de digitação)."
    )

    await update.message.reply_text(
        mensagem,
        reply_markup=obter_menu_principal(),
        parse_mode="HTML"
    )


# --- TECLADO E LÓGICA COMERCIAL DE PLANOS ---
async def obter_menu_planos(user_id: int) -> InlineKeyboardMarkup:
    """Gera os botões de planos verificando se a degustação foi usada no Supabase."""
    ja_usou_degustacao = False

    try:
        res = (
            supabase.table("assinaturas")
            .select("usou_degustacao", "tipo_plano")
            .eq("chat_id", str(user_id))
            .execute()
        )
        if res.data:
            for row in res.data:
                if (
                    row.get("usou_degustacao") is True
                    or row.get("tipo_plano") == "degustacao"
                ):
                    ja_usou_degustacao = True
                    break
    except Exception as e:
        logger.error(f"Erro ao verificar degustação no Supabase: {e}")
        ja_usou_degustacao = True  # Fallback de segurança em caso de erro na conexão

    keyboard = []

    if not ja_usou_degustacao:
        keyboard.append([
            InlineKeyboardButton(
                "🎁 Plano Degustação (Grátis)", callback_data="plano_degustacao"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "⭐ Plano Semestral (R$ 9,99)", callback_data="plano_semestral"
        )
    ])
    keyboard.append([
        InlineKeyboardButton(
            "🚀 Plano Anual (R$ 14,99)", callback_data="plano_anual"
        )
    ])
    keyboard.append([
        InlineKeyboardButton(
            "💬 Falar com Comercial", url="https://wa.me/5586994083113"
        )
    ])

    return InlineKeyboardMarkup(keyboard)

def usuario_tem_acesso(plano_info: dict) -> bool:
    """Valida se o usuário possui acesso liberado (Cortesia, Degustação ou Pago)."""
    status_bruto = str(plano_info.get("status", "")).strip().lower()
    tipo_plano = str(plano_info.get("tipo_plano", "")).strip().lower()
    usou_degustacao = plano_info.get("usou_degustacao", False)

    is_cortesia = tipo_plano == "cortesia"
    is_degustacao = tipo_plano == "degustacao"

    return (
        is_cortesia
        or (is_degustacao and (usou_degustacao or status_bruto == "ativo"))
        or (status_bruto == "ativo")
    )


async def comando_planos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe o menu de planos adaptado para Degustação, Cortesia VIP, Pago ou Sem Plano."""
    user_id = update.effective_user.id
    chat_id_str = str(user_id)

    # Consulta a assinatura no Supabase ordenando do mais recente para o mais antigo
    try:
        res = (
            supabase.table("assinaturas")
            .select("*")
            .eq("chat_id", chat_id_str)
            .order("created_at", desc=True)
            .execute()
        )
        dados = res.data if res and hasattr(res, "data") else []
    except Exception as e:
        logger.error(f"Erro ao consultar assinaturas para {chat_id_str}: {e}")
        dados = []

    plano_info = dados[0] if dados else {}
    
    # Tratamento flexível de variáveis
    tipo_plano = str(plano_info.get("tipo_plano", "")).strip().lower()
    is_cortesia = tipo_plano == "cortesia"
    is_degustacao = tipo_plano == "degustacao"

    # Usa a função centralizada que criamos
    is_ativo = usuario_tem_acesso(plano_info)

    # CENÁRIO 1: Cortesia VIP ou Plano Pago Ativo
    if is_ativo and not is_degustacao:
        tipo_formatado = "Cortesia VIP 👑" if is_cortesia else f"Pro ({tipo_plano.capitalize()})"
        limite = plano_info.get("limite_ids", "Ilimitado")

        texto = (
            "✨ <b>Sua Assinatura está Ativa!</b>\n\n"
            f"• <b>Plano Atual:</b> {tipo_formatado}\n"
            "• <b>Status:</b> Ativo 🟢\n"
            f"• <b>Limite de Monitoramentos:</b> {limite}\n\n"
            "Você já conta com acesso completo para acompanhar suas consultas e exames!"
        )
        teclado = None

    # CENÁRIO 2: Plano Degustação Ativo
    elif is_ativo and is_degustacao:
        texto = (
            "🎁 <b>Você está utilizando o Plano Degustação (Grátis)!</b>\n\n"
            "Seu período de teste está <b>ativo</b> no AlertaSUS.\n"
            "• <b>Limite Atual:</b> Até 2 regulações cadastradas\n\n"
            "💡 <i>Se desejar ampliar seu limite de monitoramentos, consulte nossos planos Pro abaixo:</i>"
        )
        teclado = await obter_menu_planos(user_id)

    # CENÁRIO 3: Sem Plano / Expirado
    else:
        texto = (
            "💳 <b>Planos e Assinaturas — AlertaSUS</b>\n\n"
            "Acompanhe suas consultas e exames sem preocupações. Escolha o plano ideal "
            "para você e receba notificações instantâneas no seu Telegram assim que sua regulação andar!\n\n"
            "<i>Selecione uma das opções abaixo para ver mais detalhes:</i>"
        )
        teclado = await obter_menu_planos(user_id)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(texto, parse_mode="HTML", reply_markup=teclado)
    else:
        await update.message.reply_text(texto, parse_mode="HTML", reply_markup=teclado)


async def detalhar_plano(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ativa a degustação ou exibe opções de pagamento via Pix."""
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass

    data = query.data
    telegram_id = query.from_user.id

    if data == "plano_degustacao":
        try:
            supabase.table("assinaturas").upsert(
                {
                    "chat_id": str(telegram_id),
                    "tipo_plano": "degustacao",
                    "status": "ativo",
                    "limite_ids": 2,
                    "usou_degustacao": True,
                },
                on_conflict="chat_id",
            ).execute()
            logger.info(f"✅ Degustação ativada no Supabase para: {telegram_id}")
        except Exception as err:
            logger.error(f"❌ Erro ao gravar degustação no Supabase: {err}")

        texto = (
            "🎁 <b>Plano Degustação Ativado!</b>\n\n"
            "Seu período de teste gratuito já está funcionando.\n\n"
            "• <b>Status:</b> Ativo\n"
            "• <b>Capacidade:</b> Até 2 regulações cadastradas\n"
            "• <b>Alertas:</b> Notificações diretas no Telegram\n\n"
            "Aproveite os recursos da plataforma!"
        )

        keyboard_botoes = [
            [InlineKeyboardButton("⚡ Ver Planos Pro", callback_data="planos")]
        ]

    elif data == "plano_semestral":
        texto = (
            "⭐ <b>Plano Semestral</b>\n\n"
            "• <b>Monitoramento Contínuo:</b> Notificações automáticas via Telegram.\n"
            "• <b>Capacidade:</b> Até 5 regulações cadastradas.\n\n"
            "<b>Valor:</b> R$ 9,99 / semestre"
        )
        keyboard_botoes = [
            [InlineKeyboardButton("💳 Pagar via Pix", callback_data="pix_pro_semestral")],
            [InlineKeyboardButton("⬅️ Voltar aos Planos", callback_data="planos")],
        ]

    elif data == "plano_anual":
        texto = (
            "🚀 <b>Plano Anual</b>\n\n"
            "• <b>Monitoramento Contínuo:</b> Notificações automáticas por 12 meses.\n"
            "• <b>Capacidade Ampliada:</b> Até 9 regulações cadastradas.\n\n"
            "<b>Valor:</b> R$ 14,99 / ano"
        )
        keyboard_botoes = [
            [InlineKeyboardButton("💳 Pagar via Pix", callback_data="pix_pro_anual")],
            [InlineKeyboardButton("⬅️ Voltar aos Planos", callback_data="planos")],
        ]
    else:
        texto = "Opção inválida."
        keyboard_botoes = [
            [InlineKeyboardButton("⬅️ Voltar", callback_data="planos")]
        ]

    await query.edit_message_text(
        text=texto,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard_botoes),
    )


# --- COMANDO DE PRIVACIDADE ---
async def comando_privacidade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe os Termos de Uso e Política de Privacidade oficiais do AlertaSUS."""
    texto = (
        "🔒 <b>Política de Privacidade e Termos de Uso — AlertaSUS</b>\n\n"
        "O <b>AlertaSUS</b> é uma ferramenta independente desenvolvida para facilitar o "
        "acompanhamento e a notificação de status de solicitações de regulação (consultas, "
        "exames e procedimentos) junto aos sistemas públicos de saúde.\n\n"
        "<b>1. Proteção de Dados (LGPD)</b>\n"
        "• Dados como CPF e número do Cartão SUS são utilizados <b>exclusivamente</b> para "
        "consultar a situação do seu agendamento nos portais oficiais de regulação.\n"
        "• Suas informações sensíveis de saúde são criptografadas e mantidas em ambiente seguro.\n"
        "• Não comercializamos nem compartilhamos seus dados com terceiros.\n\n"
        "<b>2. Isenção de Responsabilidade</b>\n"
        "• O AlertaSUS <b>não possui vínculo oficial</b> com o Ministério da Saúde ou secretarias de saúde.\n"
        "• A responsabilidade pelo agendamento, marcação e atendimento é exclusivamente das centrais de regulação do SUS.\n"
        "• Notificamos você assim que houver alteração nos sistemas públicos, mas não alteramos posições ou filas de espera.\n\n"
        "<b>3. Seus Direitos</b>\n"
        "• Você tem total autonomia para excluir suas consultas e dados cadastrados a qualquer momento através do menu do bot.\n\n"
        "<i>Ao utilizar o AlertaSUS, você declara estar de acordo com estes termos.</i>"
    )

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Dúvidas / Suporte", url="https://t.me/seu_suporte")]
    ])

    if update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(
                texto, parse_mode="HTML", reply_markup=teclado
            )
        except Exception as e:
            logger.error(f"Erro ao editar mensagem de privacidade: {e}")
            await update.callback_query.message.reply_text(
                texto, parse_mode="HTML", reply_markup=teclado
            )
    else:
        await update.message.reply_text(
            texto, parse_mode="HTML", reply_markup=teclado
        )


# --- VARREDURA AUTOMÁTICA ---
async def executar_varredura_automatica(context: ContextTypes.DEFAULT_TYPE):
    """Executa a verificação periódica e notifica mudanças no Supabase."""
    logger.info("Iniciando varredura automática de rotina detalhada...")
    try:
        regulacoes = buscar_todas_regulacoes_ativas()
        if not regulacoes:
            logger.info("Nenhuma regulação ativa encontrada para monitorar.")
            return

        for reg in regulacoes:
            num_reg = (
                reg.get("numero_reg")
                or reg.get("numero_regulacao")
                or reg.get("id_regulacao")
            )
            chat_id = (
                reg.get("chat_id")
                or reg.get("id_do_chat")
                or reg.get("telegram_id")
            )
            status_antigo = (
                reg.get("status_anterior")
                or reg.get("status_atual")
                or "PENDENTE"
            )

            if not num_reg or not chat_id:
                continue

            try:
                resultado_fms = await consultar_status_fms(str(num_reg))
            except Exception as err_sc:
                logger.error(
                    f"Erro ao consultar FMS para regulação {num_reg}: {err_sc}"
                )
                resultado_fms = None

            if isinstance(resultado_fms, dict) and resultado_fms.get("sucesso"):
                status_novo = (
                    resultado_fms.get("situacao") or "Informada no portal"
                )
            else:
                status_novo = None

            if (
                status_novo
                and str(status_novo).strip().upper()
                != str(status_antigo).strip().upper()
            ):
                try:
                    if asyncio.iscoroutinefunction(atualizar_campo_regulacao):
                        await atualizar_campo_regulacao(
                            num_reg, "status_anterior", status_novo
                        )
                    else:
                        atualizar_campo_regulacao(
                            num_reg, "status_anterior", status_novo
                        )
                    logger.info(
                        f"Status da regulação {num_reg} atualizado no Supabase para: {status_novo}"
                    )
                except Exception as err_upd:
                    logger.error(
                        f"Erro ao atualizar status no Supabase: {err_upd}"
                    )

                nome_paciente = reg.get("nome_paciente") or "Não informado"
                cartao_sus = reg.get("numero_sus") or "Não informado"
                procedimento = reg.get("procedimento") or "Não informado"
                cbo = reg.get("cbo") or "Não informado"
                celular = reg.get("celular") or "Não informado"

                header_alerta = (
                    "🚨 <b>ALERTA DE ATUALIZAÇÃO NO SUS</b> 🚨\n\n"
                    f"<b>ID da Regulação:</b> <code>{escape(str(num_reg))}</code>\n"
                    f"📌 <b>Status Anterior:</b> {escape(str(status_antigo))}\n"
                    f"📌 <b>Novo Status:</b> <b>{escape(str(status_novo))}</b>\n"
                    "───────────────────────────\n"
                    "📋 <b>FICHA CADASTRAL (SUPABASE)</b>\n"
                    f"👤 <b>Paciente:</b> {escape(str(nome_paciente))}\n"
                    f"💳 <b>Cartão SUS:</b> {escape(str(cartao_sus))}\n"
                    f"🩺 <b>Procedimento:</b> {escape(str(procedimento))}\n"
                    f"🏷️ <b>CBO:</b> {escape(str(cbo))}\n"
                    f"📱 <b>Celular:</b> {escape(str(celular))}\n"
                    "───────────────────────────"
                )

                detalhes_fms = ""
                if isinstance(resultado_fms, dict) and resultado_fms.get(
                    "sucesso"
                ):
                    detalhes_fms = "\n\n🏥 <b>SITUAÇÃO NO PORTAL FMS</b>\n"
                    alerta_fms = resultado_fms.get(
                        "alerta_fms"
                    ) or resultado_fms.get("alerta")
                    if alerta_fms:
                        detalhes_fms += f"⚠️ <b>AVISO DO PORTAL:</b>\n<i>{escape(str(alerta_fms))}</i>\n\n"

                    if resultado_fms.get("data_consulta"):
                        detalhes_fms += f"• <b>Data/Hora:</b> {escape(str(resultado_fms.get('data_consulta')))}\n"
                        detalhes_fms += f"• <b>Local:</b> {escape(str(resultado_fms.get('estabelecimento') or 'Não informado'))}\n"
                        detalhes_fms += f"• <b>Endereço:</b> {escape(str(resultado_fms.get('endereco') or 'Não informado'))}\n"
                    else:
                        posicao = (
                            resultado_fms.get("posicao_fila")
                            or "Não informada"
                        )
                        previsao = (
                            resultado_fms.get("previsao_atendimento")
                            or "Não informada"
                        )
                        detalhes_fms += (
                            f"• <b>Posição na Fila:</b> {escape(str(posicao))}\n"
                        )
                        detalhes_fms += f"• <b>Previsão de Atendimento:</b> {escape(str(previsao))}\n"

                msg_completa = header_alerta + detalhes_fms

                try:
                    await context.bot.send_message(
                        chat_id=chat_id, text=msg_completa, parse_mode="HTML"
                    )
                    logger.info(
                        f"Notificação enviada para o chat_id {chat_id}."
                    )
                except Forbidden:
                    logger.warning(
                        f"🚫 O usuário {chat_id} bloqueou o bot. Desativando."
                    )
                    desativar_regulacoes_por_chat_id(chat_id)
                except TelegramError as te:
                    logger.error(
                        f"Erro Telegram ao enviar para {chat_id}: {te}"
                    )
                except Exception as e:
                    logger.error(f"Erro ao enviar para {chat_id}: {e}")

            await asyncio.sleep(0.1)

    except Exception as e:
        logger.error(f"Erro durante a varredura automática: {e}")


# --- ALIASES ---
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


# --- MENU FLUTUANTE DE COMANDOS DO TELEGRAM ---
async def configurar_menu_comandos(app):
    """Configura o menu de comandos oficial do Telegram."""
    comandos = [
        BotCommand("iniciar", "🚀 Menu principal e boas-vindas"),
        BotCommand("verificar_todos", "🔍 Verificar todas as regulações"),
        BotCommand("verificar_especifico", "🎯 Verificar regulação específica"),
        BotCommand("cadastrar_nova", "➕ Cadastrar nova regulação"),
        BotCommand("corrigir", "✏️ Corrigir dados de regulação"),
        BotCommand("planos", "💳 Ver planos e assinaturas"),
        BotCommand("excluir", "🗑️ Excluir uma regulação"),
        BotCommand("privacidade", "🔒 Política de privacidade e LGPD"),
        BotCommand("ajuda", "❓ Central de ajuda e suporte"),
    ]
    await app.bot.set_my_commands(comandos)


# --- CONVERSATION HANDLERS ---
conv_consulta_especifica = ConversationHandler(
    entry_points=[
        CommandHandler("consultar", iniciar_verificar_especifico),
        CommandHandler("verificar_especifico", iniciar_verificar_especifico),
        CallbackQueryHandler(
            iniciar_verificar_especifico, pattern="^verificar_especifico$"
        ),
    ],
    states={
        CONSULTAR_ID: [
            CallbackQueryHandler(processar_verificar_especifico),
            MessageHandler(
                filters.TEXT & ~filters.COMMAND, processar_verificar_especifico
            ),
        ]
    },
    fallbacks=[CommandHandler("cancelar", cancelar_operacao)],
    per_message=False,
)

conv_cadastro = ConversationHandler(
    entry_points=[
        CommandHandler("cadastrar", iniciar_cadastro_manual),
        CommandHandler("cadastrar_nova", iniciar_cadastro_manual),
        CallbackQueryHandler(
            iniciar_cadastro_manual, pattern="^cadastrar_nova$"
        ),
    ],
    states={
        ETAPA_SUS: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receber_sus)
        ],
        ETAPA_NOME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receber_nome)
        ],
        ETAPA_CELULAR: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receber_celular)
        ],
        ETAPA_NASCIMENTO: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receber_nascimento)
        ],
        ETAPA_REGULACAO: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receber_regulacao)
        ],
        ETAPA_CBO: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receber_cbo)
        ],
        ETAPA_PROCEDIMENTO: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND, receber_procedimento
            )
        ],
        ETAPA_LGPD: [CallbackQueryHandler(finalizar_cadastro)],
    },
    fallbacks=[
        CommandHandler("cancelar", cancelar_operacao),
        MessageHandler(
            filters.Regex("^🚫 Cancelar Operação$"), cancelar_operacao
        ),
    ],
    per_message=False,
)

conv_corrigir = ConversationHandler(
    entry_points=[
        CommandHandler("corrigir", iniciar_corrigir),
        CallbackQueryHandler(iniciar_corrigir, pattern="^corrigir$"),
    ],
    states={
        SELECIONAR_REGULACAO: [
            CallbackQueryHandler(
                selecionar_regulacao_callback,
                pattern="^(corr_reg_|cancelar_corr)",
            )
        ],
        SELECIONAR_CAMPO: [
            CallbackQueryHandler(
                selecionar_campo_callback,
                pattern="^(form_edit_|form_salvar_|corr_campo_|cancelar_corr)",
            )
        ],
        AGUARDAR_NOVO_VALOR: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, salvar_novo_valor)
        ],
    },
    fallbacks=[CommandHandler("cancelar", cancelar_operacao)],
    per_message=False,
)

conv_excluir = ConversationHandler(
    entry_points=[
        CommandHandler("excluir", iniciar_excluir),
        CallbackQueryHandler(iniciar_excluir, pattern="^excluir$"),
    ],
    states={
        SELECIONAR_REGULACAO_EXCLUIR: [
            CallbackQueryHandler(
                selecionar_regulacao_excluir_callback,
                pattern="^(excl_reg_|cancelar_excl)",
            )
        ],
        CONFIRMAR_EXCLUSAO: [
            CallbackQueryHandler(
                confirmar_exclusao_callback,
                pattern="^(conf_excl_sim|cancelar_excl)",
            )
        ],
    },
    fallbacks=[CommandHandler("cancelar", cancelar_operacao)],
    per_message=False,
)


# --- PROCESSADOR DE CLIQUES E TEXTOS DO MENU ---
async def tratar_menu_interativo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mapeia comandos digitados para as devidas funções."""
    if not update.message or not update.message.text:
        return

    if context.user_data.get("em_fluxo") or context.user_data.get("aguardando_input"):
        return

    texto = update.message.text.strip().lower()

    if any(k in texto for k in ["início", "inicio", "menu principal", "/iniciar"]):
        await start(update, context)
    elif any(k in texto for k in ["corrigir", "corrigir id", "/corrigir"]):
        await iniciar_corrigir(update, context)
    elif any(k in texto for k in ["cadastrar nova", "cadastrar", "/cadastrar_nova"]):
        await iniciar_cadastro_manual(update, context)
    elif any(k in texto for k in ["verificar todas", "verificar_todos", "/verificar_todos"]):
        await comando_verificar_todas(update, context)
    elif any(k in texto for k in ["verificar específica", "verificar especifica", "específica", "/verificar_especifico"]):
        await iniciar_verificar_especifico(update, context)
    elif any(k in texto for k in ["planos", "assinaturas", "/planos"]):
        await comando_planos(update, context)
    elif any(k in texto for k in ["excluir", "/excluir"]):
        await iniciar_excluir(update, context)
    elif any(k in texto for k in ["privacidade", "lgpd", "/privacidade"]):
        await comando_privacidade(update, context)
    elif any(k in texto for k in ["ajuda", "suporte", "/ajuda", "/suporte"]):
        await comando_ajuda(update, context)
    elif any(k in texto for k in ["cancelar", "cancelar operação", "/cancelar"]):
        await update.message.reply_text("❌ Operação cancelada.")
    else:
        if texto.isdigit() and len(texto) >= 10:
            return

        await update.message.reply_text(
            "⚠️ Opção não reconhecida.\n\n"
            "Por favor, acesse as opções pelo menu nativo do Telegram (botão [/]).",
            parse_mode="HTML"
        )


# --- EXPORTAÇÃO DE SÍMBOLOS DO HANDLER ---
__all__ = [
    "CONSULTAR_ID",
    "SELECIONAR_REGULACAO",
    "SELECIONAR_CAMPO",
    "AGUARDAR_NOVO_VALOR",
    "SELECIONAR_REGULACAO_EXCLUIR",
    "CONFIRMAR_EXCLUSAO",
    "ETAPA_SUS",
    "ETAPA_NOME",
    "ETAPA_CELULAR",
    "ETAPA_NASCIMENTO",
    "ETAPA_REGULACAO",
    "ETAPA_CBO",
    "ETAPA_PROCEDIMENTO",
    "ETAPA_LGPD",
    "start",
    "comando_ajuda",
    "comando_privacidade",
    "comando_planos",
    "cancelar_operacao",
    "configurar_menu_comandos",
    "executar_varredura_automatica",
    "comando_verificar_todas",
    "iniciar_verificar_especifico",
    "processar_verificar_especifico",
    "iniciar_cadastro_manual",
    "receber_sus",
    "receber_nome",
    "receber_celular",
    "receber_nascimento",
    "receber_regulacao",
    "receber_cbo",
    "receber_procedimento",
    "finalizar_cadastro",
    "iniciar_corrigir",
    "selecionar_regulacao_callback",
    "selecionar_campo_callback",
    "salvar_novo_valor",
    "cancelar_corrigir",
    "iniciar_excluir",
    "selecionar_regulacao_excluir_callback",
    "confirmar_exclusao_callback",
    "cancelar_excluir",
    "conv_consulta_especifica",
    "conv_cadastro",
    "conv_corrigir",
    "conv_excluir",
    "tratar_menu_interativo",
    "obter_menu_principal",
    "obter_menu_planos",
    "detalhar_plano",
    "processar_pix_callback",
]

async def callback_ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Responde ao clique no botão Ajuda com o script da Central de Atendimento Automatizado."""
    query = update.callback_query
    await query.answer()

    # Script de atendimento corrigido
    script_atendimento = (
        "🤖 <b>Central de Atendimento Automatizado — AlertaSUS</b>\n\n"
        "Seja bem-vindo(a) ao suporte do AlertaSUS! Nosso sistema automatizado está pronto "
        "para auxiliar você com rapidez e precisão.\n\n"
        "📌 <b>O que você pode fazer por aqui?</b>\n"
        "• Consultar o status das suas regulações ativas.\n"
        "• Tirar dúvidas sobre planos e renovação de assinatura.\n"
        "• Obter orientações sobre a consulta via Cartão SUS ou ID da Regulação.\n"
        "• Notificar divergências ou solicitar suporte técnico no sistema.\n\n"
        "💡 <b>Como iniciar?</b>\n"
        "Acesse nossa central dedicada abaixo para ser atendido pelo nosso assistente:"
    )

    teclado = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🤖 Central de Atendimento ao Usuário AlertaSUS 2.0",
                url="https://t.me/AlertaSUS_Atendimento_ao_Usuario"
            )
        ],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="voltar_inicio")]
    ])

    await query.edit_message_text(
        script_atendimento,
        parse_mode="HTML",
        reply_markup=teclado
    )

    