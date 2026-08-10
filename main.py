import os
import logging
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters
)

from config import TELEGRAM_BOT_TOKEN

# --------------------------------------------------
# IMPORTAÇÕES MODULARIZADAS
# --------------------------------------------------

# Handlers Base
from handlers_base import (
    start,
    comando_ajuda,
    cancelar_operacao,
    configurar_menu_comandos,
    executar_varredura_automatica
)

# Handlers de Cadastro
from handlers_cadastro import (
    ETAPA_SUS,
    ETAPA_NOME,
    ETAPA_CELULAR,
    ETAPA_NASCIMENTO,
    ETAPA_REGULACAO,
    ETAPA_CBO,
    ETAPA_PROCEDIMENTO,
    ETAPA_LGPD,
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

# Handlers de Consulta
from handlers_consulta import (
    comando_verificar_todas,
    iniciar_verificar_especifico,
    processar_verificar_especifico
)

# Utilitários e Estados
from handlers_utils import CONSULTAR_ID

# Handlers de Consulta
from handlers_base import executar_varredura_automatica
    CONSULTAR_ID,
    comando_verificar_todas,
    iniciar_verificar_especifico,
    processar_verificar_especifico,
)

# Handlers de Correção
from handlers_correcao import (
    SELECIONAR_REGULACAO,
    SELECIONAR_CAMPO,
    AGUARDAR_NOVO_VALOR,
    iniciar_corrigir,
    selecionar_regulacao_callback,
    selecionar_campo_callback,
    salvar_novo_valor,
    cancelar_corrigir
)

# Handlers de Exclusão
from handlers_exclusao import (
    SELECIONAR_REGULACAO_EXCLUIR,
    CONFIRMAR_EXCLUSAO,
    iniciar_excluir,
    selecionar_regulacao_excluir_callback,
    confirmar_exclusao_callback,
    cancelar_excluir
)


# Configuração de Logs
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# --------------------------------------------------
# CONVERSAÇÕES
# --------------------------------------------------

# 1. Cadastro Interativo no Telegram
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

# 2. Verificar Específico (Com suporte a seleção por Botões Inline e digitação manual)
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

# 4. Excluir Regulação Interativa por Botões
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
# MAIN
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