import logging
from telegram import BotCommand
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes
)

# Importa o token do seu arquivo de configuração
from config import TELEGRAM_BOT_TOKEN

# Configuração do intervalo de varredura (em minutos)
VARREDURA_INTERVALO_MINUTOS = 60

logger = logging.getLogger(__name__)

# Importa as rotas organizadas nos 3 módulos
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

# --- FUNÇÃO DE VARREDURA AUTOMÁTICA ---
async def executar_varredura_automatica(context: ContextTypes.DEFAULT_TYPE):
    """Executa a verificação periódica de todas as regulações cadastradas."""
    logger.info("Iniciando varredura automática de rotina...")
    # Se você possuir a lógica de varredura em handlers_consultas, chame-a aqui.

# --- ALIASES PARA COMPATIBILIDADE COM MAIN.PY ---
cancelar_corrigir = cancelar_operacao
cancelar_excluir = cancelar_operacao
cancelar_cadastro = cancelar_operacao

# --- FUNÇÃO EXPORTADA PARA O MAIN.PY ---
async def configurar_menu_comandos(app):
    """Configura a lista de comandos no menu do Telegram."""
    comandos = [
        BotCommand("start", "Inicia o bot e exibe o menu principal"),
        BotCommand("verificar", "Verifica todas as regulações cadastradas"),
        BotCommand("consultar", "Consulta o status de uma regulação específica"),
        BotCommand("cadastrar", "Cadastra uma nova regulação"),
        BotCommand("corrigir", "Corrige dados de uma regulação"),
        BotCommand("excluir", "Exclui uma regulação do monitoramento"),
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

# --- INICIALIZAÇÃO DO BOT ---

def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Agendamento da varredura automática em background
    if app.job_queue:
        app.job_queue.run_repeating(
            executar_varredura_automatica,
            interval=VARREDURA_INTERVALO_MINUTOS * 60,
            first=10
        )

    # Registro de Comandos Simples
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", comando_ajuda))
    app.add_handler(MessageHandler(filters.Regex("^ℹ️ Ajuda$"), comando_ajuda))
    app.add_handler(CommandHandler("verificar", comando_verificar_todas))
    app.add_handler(MessageHandler(filters.Regex("^📋 Verificar Todas$"), comando_verificar_todas))

    # Registro dos Fluxos Módulos (Conversations)
    app.add_handler(conv_consulta_especifica)
    app.add_handler(conv_cadastro)
    app.add_handler(conv_corrigir)
    app.add_handler(conv_excluir)

    print("🤖 Bot iniciado e pronto para uso!")
    app.run_polling()

if __name__ == "__main__":
    main()