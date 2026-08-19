import logging
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from config import TELEGRAM_BOT_TOKEN
from handler import (
    comando_planos,
    comando_privacidade,
    comando_verificar_todas,
    conv_cadastro,
    conv_consulta_especifica,
    conv_corrigir,
    conv_excluir,
    detalhar_plano,
    iniciar_cadastro_manual,
    iniciar_corrigir,
    iniciar_excluir,
    iniciar_verificar_especifico,
    processar_pix_callback,
    start,
    tratar_menu_interativo,
)
# Importações da Central de Suporte Automatizada por Tickets
from suporte import (
    AGUARDANDO_MENSAGEM,
    cancelar_suporte,
    conv_suporte,
    menu_suporte,
    receber_mensagem_suporte,
    responder_chamado_admin,
)

# Importações dos handlers de administração
from handler_admin import (
    comando_conceder_cortesia,
    comando_remover_cortesia,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)  # <-- ESTA LINHA ADICIONADA AQUI RESOLVE TUDO!


def main():
    # Configura tempos limite para conexões instáveis e previne o erro TimedOut
    request_config = HTTPXRequest(
        connect_timeout=20.0,
        read_timeout=20.0,
        write_timeout=20.0,
        pool_timeout=20.0,
    )

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .request(request_config)
        .build()
    )

    # 1. Fluxos Conversacionais
    app.add_handler(conv_consulta_especifica)
    app.add_handler(conv_cadastro)
    app.add_handler(conv_corrigir)
    app.add_handler(conv_excluir)
    app.add_handler(conv_suporte)

    # 2. Comandos Principais
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("iniciar", start))
    app.add_handler(CommandHandler("cadastrar_nova", iniciar_cadastro_manual))
    app.add_handler(CommandHandler("verificar_todos", comando_verificar_todas))
    app.add_handler(CommandHandler("verificar_especifico", iniciar_verificar_especifico))
    app.add_handler(CommandHandler("corrigir", iniciar_corrigir))
    app.add_handler(CommandHandler("excluir", iniciar_excluir))
    app.add_handler(CommandHandler("planos", comando_planos))
    app.add_handler(CommandHandler("privacidade", comando_privacidade))
    app.add_handler(CommandHandler("ajuda", menu_suporte))
    app.add_handler(CommandHandler("suporte", menu_suporte))

    # 3. Comandos Administrativos
    app.add_handler(CommandHandler("responder", responder_chamado_admin))
    app.add_handler(CommandHandler("conceder", comando_conceder_cortesia))
    app.add_handler(CommandHandler("remover", comando_remover_cortesia))

    # 4. Callbacks de Botões Inline
    app.add_handler(CallbackQueryHandler(detalhar_plano, pattern="^plano_"))
    app.add_handler(CallbackQueryHandler(processar_pix_callback, pattern="^pix_"))

    # Inicia o bot (DEVE estar recuado dentro do def main)
    logger.info("Bot iniciado com sucesso!")
    app.run_polling()


if __name__ == "__main__":
    main()

    # 1. FLUXOS CONVERSACIONAIS (Conversations)
    app.add_handler(conv_consulta_especifica)
    app.add_handler(conv_cadastro)
    app.add_handler(conv_corrigir)
    app.add_handler(conv_excluir)
    
    # Adiciona o fluxo de suporte vindo do suporte.py
    app.add_handler(conv_suporte)

    # 2. COMANDOS DE ADMINISTRAÇÃO
    app.add_handler(
        CommandHandler("conceder_cortesia", comando_conceder_cortesia)
    )
    app.add_handler(CommandHandler("cortesia", comando_conceder_cortesia))
    app.add_handler(
        CommandHandler("remover_cortesia", comando_remover_cortesia)
    )
    app.add_handler(CommandHandler("responder", responder_chamado_admin))

    # 3. COMANDOS DIRETOS (/comando)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("iniciar", start))
    app.add_handler(CommandHandler("verificar_todos", comando_verificar_todas))
    app.add_handler(
        CommandHandler("verificar_especifico", iniciar_verificar_especifico)
    )
    app.add_handler(CommandHandler("cadastrar_nova", iniciar_cadastro_manual))
    app.add_handler(CommandHandler("corrigir", iniciar_corrigir))
    app.add_handler(CommandHandler("planos", comando_planos))
    app.add_handler(CommandHandler("excluir", iniciar_excluir))
    app.add_handler(CommandHandler("privacidade", comando_privacidade))
    app.add_handler(CommandHandler("ajuda", menu_suporte))
    app.add_handler(CommandHandler("suporte", menu_suporte))

    # 4. BOTÕES E CALLBACKS DO MENU / SUPORTE
    app.add_handler(CallbackQueryHandler(detalhar_plano, pattern="^plano_"))
    app.add_handler(
        CallbackQueryHandler(processar_pix_callback, pattern="^pix_")
    )
    app.add_handler(CallbackQueryHandler(comando_planos, pattern="^planos$"))
    app.add_handler(CallbackQueryHandler(start, pattern="^iniciar$"))
    app.add_handler(
        CallbackQueryHandler(
            comando_verificar_todas, pattern="^verificar_todos$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            comando_privacidade, pattern="^privacidade$"
        )
    )
    app.add_handler(CallbackQueryHandler(menu_suporte, pattern="^ajuda$"))
    

    # 5. MENSAGENS DE TEXTO (Desativado pois agora usamos comandos nativos nos botões)
    
    # Inicia o bot
    app.run_polling()


if __name__ == "__main__":
    main()
    

    # Inicia o bot
    app.run_polling()


if __name__ == "__main__":
    main()