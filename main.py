import os
import logging
from telegram.ext import (
    ApplicationBuilder,
    ConversationHandler, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler, 
    filters
)

from config import TELEGRAM_BOT_TOKEN

from handler import (
    CONSULTAR_ID, SELECIONAR_REGULACAO, SELECIONAR_CAMPO, AGUARDAR_NOVO_VALOR,
    SELECIONAR_REGULACAO_EXCLUIR, CONFIRMAR_EXCLUSAO, ETAPA_SUS, ETAPA_NOME,
    ETAPA_CELULAR, ETAPA_NASCIMENTO, ETAPA_REGULACAO, ETAPA_CBO, ETAPA_PROCEDIMENTO,
    ETAPA_LGPD, start, comando_ajuda, comando_privacidade, comando_planos,
    cancelar_operacao, configurar_menu_comandos, executar_varredura_automatica,
    comando_verificar_todas, iniciar_verificar_especifico, processar_verificar_especifico,
    iniciar_cadastro_manual, receber_sus, receber_nome, receber_celular, receber_nascimento,
    receber_regulacao, receber_cbo, receber_procedimento, finalizar_cadastro,
    iniciar_corrigir, selecionar_regulacao_callback, selecionar_campo_callback,
    salvar_novo_valor, iniciar_excluir, selecionar_regulacao_excluir_callback,
    confirmar_exclusao_callback, conv_cadastro, conv_consulta_especifica, conv_corrigir, conv_excluir
)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(configurar_menu_comandos).build()

    app.add_handler(conv_cadastro)
    app.add_handler(conv_consulta_especifica)
    app.add_handler(conv_corrigir)
    app.add_handler(conv_excluir)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex(r"^(🚀\s*)?(Início|Start)$"), start))
    app.add_handler(CommandHandler("ajuda", comando_ajuda))
    app.add_handler(MessageHandler(filters.Regex(r"^(ℹ️\s*)?Ajuda$"), comando_ajuda))
    app.add_handler(CommandHandler("privacidade", comando_privacidade))
    app.add_handler(MessageHandler(filters.Regex(r"^(📄\s*)?Privacidade$"), comando_privacidade))
    app.add_handler(CommandHandler("planos", comando_planos))
    app.add_handler(MessageHandler(filters.Regex(r"^(💎\s*)?Planos$"), comando_planos))
    app.add_handler(MessageHandler(filters.Regex("^📋 Verificar Todas$"), comando_verificar_todas))
    app.add_handler(CommandHandler("verificar_todas", comando_verificar_todas))

    if app.job_queue:
        app.job_queue.run_repeating(executar_varredura_automatica, interval=7200, first=10)

    app.run_polling()

if __name__ == "__main__":
    main()


