import os
import logging
from telegram.ext import (
    Application,
    ConversationHandler, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler, 
    filters
)

from config import TELEGRAM_BOT_TOKEN

# Importação centralizada de estados, handlers e utilitários a partir do handler.py
from handler import (
    # Estados de conversação
    CONSULTAR_ID,
    SELECIONAR_REGULACAO,
    SELECIONAR_CAMPO,
    AGUARDAR_NOVO_VALOR,
    SELECIONAR_REGULACAO_EXCLUIR,
    CONFIRMAR_EXCLUSAO,
    ETAPA_SUS,
    ETAPA_NOME,
    ETAPA_CELULAR,
    ETAPA_NASCIMENTO,
    ETAPA_REGULACAO,
    ETAPA_CBO,
    ETAPA_PROCEDIMENTO,
    ETAPA_LGPD,

    # Handlers base e automação
    start,
    comando_ajuda,
    cancelar_operacao,
    configurar_menu_comandos,
    executar_varredura_automatica,

    # Consulta
    comando_verificar_todas,
    iniciar_verificar_especifico,
    processar_verificar_especifico,

    # Cadastro
    iniciar_cadastro_manual,
    receber_sus,
    receber_nome,
    receber_celular,
    receber_nascimento,
    receber_regulacao,
    receber_cbo,
    receber_procedimento,
    finalizar_cadastro,

    # Correção
    iniciar_corrigir,
    selecionar_regulacao_callback,
    selecionar_campo_callback,
    salvar_novo_valor,
    cancelar_corrigir,

    # Exclusão
    iniciar_excluir,
    selecionar_regulacao_excluir_callback,
    confirmar_exclusao_callback,
    cancelar_excluir,
)

# Configuração do Sistema de Logs
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# --------------------------------------------------
# HANDLERS DE CONVERSAÇÃO (CONVERSATION HANDLERS)
# --------------------------------------------------

# 1. Cadastro Interativo
conv_cadastro = ConversationHandler(
    entry_points=[
        MessageHandler(filters.Regex("^➕ Cadastrar Nova$"), iniciar_cadastro_manual),
        CommandHandler("cadastrar", iniciar_cadastro_manual)
    ],
    states={
        ETAPA_SUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_sus)],
        ETAPA_NOME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_nome)],
        ETAPA_CELULAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_celular)],
        ETAPA_NASCIMENTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_nascimento)],
        ETAPA_REGULACAO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_regulacao)],
        ETAPA_CBO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_cbo)],
        ETAPA_PROCEDIMENTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_procedimento)],
        ETAPA_LGPD: [CallbackQueryHandler(finalizar_cadastro, pattern="^(aceitar_lgpd|cancelar_cadastro)$")]
    },
    fallbacks=[
        CommandHandler("cancelar", cancelar_operacao),
        MessageHandler(filters.Regex("(?i)cancelar"), cancelar_operacao)
    ],
    allow_reentry=True,
    per_message=False
)

# 2. Verificar Específico (Suporte a seleção por Botões Inline e digitação manual)
conv_verificar_especifico = ConversationHandler(
    entry_points=[
        MessageHandler(filters.Regex("^🔍 Verificar Específico$"), iniciar_verificar_especifico),
        CommandHandler("consultar", iniciar_verificar_especifico)
    ],
    states={
        CONSULTAR_ID: [
            CallbackQueryHandler(processar_verificar_especifico, pattern="^(ver_esp_|cancelar_ver_esp)$"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, processar_verificar_especifico)
        ]
    },
    fallbacks=[
        CommandHandler("cancelar", cancelar_operacao),
        MessageHandler(filters.Regex("(?i)cancelar"), cancelar_operacao)
    ],
    allow_reentry=True,
    per_message=False
)

# 3. Corrigir Dados (Central Interativa por Botões)
conv_corrigir = ConversationHandler(
    entry_points=[
        MessageHandler(filters.Regex("^✏️ Corrigir ID$"), iniciar_corrigir),
        CommandHandler("corrigir", iniciar_corrigir)
    ],
    states={
        SELECIONAR_REGULACAO: [
            CallbackQueryHandler(selecionar_regulacao_callback)
        ],
        SELECIONAR_CAMPO: [
            CallbackQueryHandler(selecionar_campo_callback)
        ],
        AGUARDAR_NOVO_VALOR: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, salvar_novo_valor)
        ]
    },
    fallbacks=[
        CommandHandler("cancelar", cancelar_corrigir),
        MessageHandler(filters.Regex("^🚫 Cancelar Operação$"), cancelar_corrigir)
    ],
    allow_reentry=True,
    per_message=False
)

# 4. Excluir Regulação Interativa
conv_excluir = ConversationHandler(
    entry_points=[
        MessageHandler(filters.Regex("(?i)Excluir"), iniciar_excluir),
        CommandHandler("excluir", iniciar_excluir)
    ],
    states={
        SELECIONAR_REGULACAO_EXCLUIR: [
            CallbackQueryHandler(selecionar_regulacao_excluir_callback)
        ],
        CONFIRMAR_EXCLUSAO: [
            CallbackQueryHandler(confirmar_exclusao_callback)
        ]
    },
    fallbacks=[
        CommandHandler("cancelar", cancelar_excluir),
        MessageHandler(filters.Regex("(?i)cancelar"), cancelar_excluir)
    ],
    allow_reentry=True,
    per_message=False
)

# --------------------------------------------------
# MAIN (INICIALIZAÇÃO DO BOT)
# --------------------------------------------------

def main():
    if not TELEGRAM_BOT_TOKEN:
        logging.error("TELEGRAM_BOT_TOKEN não foi configurado.")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Adição dos Handlers de Conversação ao App
    app.add_handler(conv_cadastro)
    app.add_handler(conv_verificar_especifico)
    app.add_handler(conv_corrigir)
    app.add_handler(conv_excluir)

    # Handlers Diretos e Comandos de Menu
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", comando_ajuda))
    app.add_handler(CommandHandler("verificar", comando_verificar_todas))

    app.add_handler(MessageHandler(filters.Regex("^📋 Verificar Todas$"), comando_verificar_todas))
    app.add_handler(MessageHandler(filters.Regex("^ℹ️ Ajuda$"), comando_ajuda))

    # Configura o menu de comandos azul do Telegram ao iniciar
    app.post_init = configurar_menu_comandos

    print("🚀 AlertaSUS 2.0 pronto e rodando!", flush=True)
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()