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
    buscar_todas_regulacoes_ativas,
    atualizar_campo_regulacao,
    desativar_regulacoes_por_chat_id
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
    start,
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


# --- COMANDO DE PRIVACIDADE ---
async def comando_privacidade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe o link direto para o Termo de Consentimento e Política de Privacidade."""
    keyboard = [[InlineKeyboardButton("📄 Consultar Termo e Política", url=URL_TERMO_LGPD)]]
    await update.message.reply_text(
        "📋 <b>Termo de Consentimento e Política de Privacidade</b>\n\n"
        "Você pode consultar nosso documento completo sempre que desejar pelo link abaixo:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# --- VARREDURA AUTOMÁTICA DETALHADA E SEM MÁSCARAS ---
async def executar_varredura_automatica(context: ContextTypes.DEFAULT_TYPE):
    """Executa a verificação periódica e envia o relatório apenas se houver MUDANÇA REAL de status no Supabase."""
    logger.info("Iniciando varredura automática de rotina detalhada...")
    try:
        regulacoes = await buscar_todas_regulacoes_ativas()
        if not regulacoes:
            logger.info("Nenhuma regulação ativa encontrada para monitorar.")
            return

        for reg in regulacoes:
            num_reg = reg.get("numero_reg") or reg.get("numero_regulacao") or reg.get("id_regulacao")
            chat_id = reg.get("chat_id") or reg.get("id_do_chat") or reg.get("telegram_id")
            
            # Prioriza 'status_anterior', que é o nome real da coluna na sua tabela AlertaSUS_2.0
            status_antigo = reg.get("status_anterior") or reg.get("status_atual") or "PENDENTE"

            if not num_reg or not chat_id:
                continue

            # 1. Consulta os detalhes completos no portal FMS via scraper
            try:
                resultado_fms = await consultar_status_fms(str(num_reg))
            except Exception as err_sc:
                logger.error(f"Erro ao consultar FMS para regulação {num_reg}: {err_sc}")
                resultado_fms = None

            # Determina o novo status retornado pela consulta
            if isinstance(resultado_fms, dict) and resultado_fms.get("sucesso"):
                status_novo = resultado_fms.get("situacao") or "Informada no portal"
            else:
                status_novo = None

            # 2. Se houver mudança de status, dispara o relatório e ATUALIZA o Supabase
            if status_novo and str(status_novo).strip().upper() != str(status_antigo).strip().upper():
                
                # CRÍTICO: Atualiza na coluna correta ('status_anterior') no Supabase
                try:
                    if asyncio.iscoroutinefunction(atualizar_campo_regulacao):
                        await atualizar_campo_regulacao(num_reg, "status_anterior", status_novo)
                    else:
                        atualizar_campo_regulacao(num_reg, "status_anterior", status_novo)
                    logger.info(f"Status da regulação {num_reg} atualizado no Supabase para: {status_novo}")
                except Exception as err_upd:
                    logger.error(f"Erro ao atualizar status no Supabase: {err_upd}")

                # Extrai a ficha cadastral completa salva no Supabase
                nome_paciente = reg.get("nome_paciente") or "Não informado"
                cartao_sus = reg.get("numero_sus") or "Não informado"
                procedimento = reg.get("procedimento") or "Não informado"
                cbo = reg.get("cbo") or "Não informado"
                celular = reg.get("celular") or "Não informado"

                # Monta o cabeçalho estruturado
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

                # Detalhes adicionais capturados direto do portal FMS
                detalhes_fms = ""
                if isinstance(resultado_fms, dict) and resultado_fms.get("sucesso"):
                    detalhes_fms = "\n\n🏥 <b>SITUAÇÃO NO PORTAL FMS</b>\n"
                    
                    alerta_fms = resultado_fms.get("alerta_fms") or resultado_fms.get("alerta")

                    if resultado_fms.get("data_consulta"):
                        detalhes_fms += f"• <b>Data/Hora:</b> {escape(str(resultado_fms.get('data_consulta')))}\n"
                        detalhes_fms += f"• <b>Local:</b> {escape(str(resultado_fms.get('estabelecimento') or 'Não informado'))}\n"
                        detalhes_fms += f"• <b>Endereço:</b> {escape(str(resultado_fms.get('endereco') or 'Não informado'))}\n"
                        if alerta_fms:
                            detalhes_fms += f"\n⚠️ <b>AVISO DO PORTAL:</b>\n<i>{escape(str(alerta_fms))}</i>\n"
                    else:
                        posicao = resultado_fms.get("posicao_fila") or "Não informada"
                        previsao = resultado_fms.get("previsao_atendimento") or "Não informada"
                        detalhes_fms += f"• <b>Posição na Fila:</b> {escape(str(posicao))}\n"
                        
                        # 💡 SE HOUVER AVISO/MENSAGEM DO PORTAL, DÁ DESTAQUE A ELA EM VEZ DE MOSTRAR APENAS A PREVISÃO
                        if alerta_fms and str(alerta_fms).strip():
                            detalhes_fms += f"\n⚠️ <b>MENSAGEM DO PORTAL:</b>\n<i>{escape(str(alerta_fms))}</i>\n"
                        else:
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

            # Pausa assíncrona para evitar rate limit
            await asyncio.sleep(0.1)

    except Exception as e:
        logger.error(f"Erro durante a execução da varredura automática: {e}")


# --- ALIASES ---
cancelar_corrigir = cancelar_operacao
cancelar_excluir = cancelar_operacao
cancelar_cadastro = cancelar_operacao


# --- CONFIGURAÇÃO DO MENU ---
async def configurar_menu_comandos(app):
    comandos = [
        BotCommand("start", "Inicia o bot e exibe o menu principal"),
        BotCommand("verificar", "Verifica todas as regulações cadastradas"),
        BotCommand("consultar", "Consulta o status de uma regulação específica"),
        BotCommand("cadastrar", "Cadastra uma nova regulação"),
        BotCommand("corrigir", "Corrige dados de uma regulação"),
        BotCommand("excluir", "Exclui uma regulação do monitoramento"),
        BotCommand("privacidade", "Termo de privacidade e LGPD"),
        BotCommand("ajuda", "Exibe ajuda e instruções de uso"),
        BotCommand("cancelar", "Cancela a operação atual")
    ]
    await app.bot.set_my_commands(comandos)


# --- CONVERSATION HANDLERS ---
conv_consulta_especifica = ConversationHandler(
    entry_points=[
        CommandHandler("consultar", iniciar_verificar_especifico),
        MessageHandler(filters.Regex("^🔍 Verificar Específico$"), iniciar_verificar_especifico)
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
        MessageHandler(filters.Regex("^➕ Cadastrar Nova$"), iniciar_cadastro_manual)
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
        MessageHandler(filters.Regex("^✏️ Corrigir ID$"), iniciar_corrigir)
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
        MessageHandler(filters.Regex("^🗑️ Excluir Regulação$"), iniciar_excluir)
    ],
    states={
        SELECIONAR_REGULACAO_EXCLUIR: [CallbackQueryHandler(selecionar_regulacao_excluir_callback, pattern="^(excl_reg_|cancelar_excl)")],
        CONFIRMAR_EXCLUSAO: [CallbackQueryHandler(confirmar_exclusao_callback, pattern="^(conf_excl_sim|cancelar_excl)")]
    },
    fallbacks=[CommandHandler("cancelar", cancelar_operacao)]
)

# Exportação explícita de símbolos do handler
__all__ = [
    "CONSULTAR_ID", "SELECIONAR_REGULACAO", "SELECIONAR_CAMPO", "AGUARDAR_NOVO_VALOR",
    "SELECIONAR_REGULACAO_EXCLUIR", "CONFIRMAR_EXCLUSAO", "ETAPA_SUS", "ETAPA_NOME",
    "ETAPA_CELULAR", "ETAPA_NASCIMENTO", "ETAPA_REGULACAO", "ETAPA_CBO", "ETAPA_PROCEDIMENTO",
    "ETAPA_LGPD", "start", "comando_ajuda", "comando_privacidade", "cancelar_operacao",
    "configurar_menu_comandos", "executar_varredura_automatica", "comando_verificar_todas",
    "iniciar_verificar_especifico", "processar_verificar_especifico", "iniciar_cadastro_manual",
    "receber_sus", "receber_nome", "receber_celular", "receber_nascimento", "receber_regulacao",
    "receber_cbo", "receber_procedimento", "finalizar_cadastro", "iniciar_corrigir",
    "selecionar_regulacao_callback", "selecionar_campo_callback", "salvar_novo_valor",
    "cancelar_corrigir", "iniciar_excluir", "selecionar_regulacao_excluir_callback",
    "confirmar_exclusao_callback", "cancelar_excluir"
]