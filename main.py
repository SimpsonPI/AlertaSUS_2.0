import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler,
    filters,
    ContextTypes
)
from handler import (
    start, 
    comando_ajuda, 
    comando_privacidade, 
    comando_planos,
    detalhar_plano,
    comando_verificar_todas, 
    configurar_menu_comandos, 
    executar_varredura_automatica, 
    conv_consulta_especifica, 
    conv_cadastro, 
    conv_corrigir, 
    conv_excluir, 
    tratar_menu_interativo,
    iniciar_verificar_especifico,
    iniciar_cadastro_manual,
    iniciar_corrigir,
    iniciar_excluir
)
from src.handlers_admin import comando_conceder_cortesia, comando_remover_cortesia
from src.handlers_pagamento import gerar_pagamento_pix

# Carrega as variáveis do arquivo .env
load_dotenv()

# Configuração de logs
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)

async def roteador_callback_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    print(f"👉 1. ROTEADOR RECEBEU: {data}")

    if data == "verificar_todos":
        await comando_verificar_todas(update, context)
    elif data == "verificar_especifico":
        await iniciar_verificar_especifico(update, context)
    elif data == "cadastrar_nova":
        await iniciar_cadastro_manual(update, context)
    elif data == "corrigir":
        await iniciar_corrigir(update, context)
    elif data == "planos":
        await comando_planos(update, context)
    elif data in ["plano_degustacao", "plano_semestral", "plano_anual"]:
        print(f"👉 2. ENTROU NO ELIF DE PLANOS PARA: {data}")
        await detalhar_plano(update, context)
        print("👉 3. SAIU DE DETALHAR_PLANO")
    elif data == "excluir":
        await iniciar_excluir(update, context)
    elif data == "privacidade":
        await comando_privacidade(update, context)
    elif data == "ajuda":
        await comando_ajuda(update, context)
    elif data == "iniciar":
        await start(update, context)
    else:
        print(f"⚠️ CALLBACK DESCONHECIDO: {data}")

async def post_init(application):
    await configurar_menu_comandos(application)

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
    
    if not token:
        raise ValueError("❌ ERRO: NENHUM TOKEN (TELEGRAM_BOT_TOKEN) FOI ENCONTRADO NO ARQUIVO .ENV!")

    app = ApplicationBuilder().token(token).post_init(post_init).build()

    # 1. CONVERSAÇÕES
    app.add_handler(conv_consulta_especifica)
    app.add_handler(conv_cadastro)
    app.add_handler(conv_corrigir)
    app.add_handler(conv_excluir)

    # 2. COMANDOS
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("iniciar", start))
    app.add_handler(CommandHandler("planos", comando_planos))
    app.add_handler(CommandHandler("ajuda", comando_ajuda))

    # 3. HANDLER DE BOTÕES
    app.add_handler(CallbackQueryHandler(gerar_pagamento_pix, pattern="^pix_"))
    app.add_handler(CallbackQueryHandler(roteador_callback_menu))

    # 4. MENSAGENS DE TEXTO
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, tratar_menu_interativo))

    # Job Queue
    if app.job_queue:
        app.job_queue.run_repeating(executar_varredura_automatica, interval=7200, first=10)

    print("🤖 Bot iniciado com sucesso!")
    app.run_polling()

    # 1. FLUXOS CONVERSACIONAIS
    app.add_handler(conv_consulta_especifica)
    app.add_handler(conv_cadastro)
    app.add_handler(conv_corrigir)
    app.add_handler(conv_excluir)

    # 1. COMANDOS DE ADMINISTRAÇÃO (Coloque no topo!)
    app.add_handler(CommandHandler("conceder_cortesia", comando_conceder_cortesia))
    app.add_handler(CommandHandler("cortesia", comando_conceder_cortesia))
    app.add_handler(CommandHandler("remover_cortesia", comando_remover_cortesia))
    
    # 2. COMANDOS DIRETOS ( /comando )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("iniciar", start))
    app.add_handler(CommandHandler("verificar_todos", comando_verificar_todas))
    app.add_handler(CommandHandler("verificar_especifico", iniciar_verificar_especifico))
    app.add_handler(CommandHandler("cadastrar_nova", iniciar_cadastro_manual))
    app.add_handler(CommandHandler("corrigir", iniciar_corrigir))
    app.add_handler(CommandHandler("planos", comando_planos))
    app.add_handler(CommandHandler("excluir", iniciar_excluir))
    app.add_handler(CommandHandler("privacidade", comando_privacidade))
    app.add_handler(CommandHandler("ajuda", comando_ajuda))
    app.add_handler(CommandHandler("pix", gerar_pagamento_pix))
    
    app.add_handler(CommandHandler("conceder_cortesia", comando_conceder_cortesia))
    app.add_handler(CommandHandler("cortesia", comando_conceder_cortesia))  # Atalho mais curto
    app.add_handler(CommandHandler("remover_cortesia", comando_remover_cortesia))

    # 3. CAPTURA DOS BOTÕES DE PAGAMENTO PIX
    app.add_handler(CallbackQueryHandler(gerar_pagamento_pix, pattern="^pix_"))

    # 4. CAPTURA GERAL DE BOTÕES INLINE DO MENU E PLANOS (Sem restrição de pattern)
    app.add_handler(CallbackQueryHandler(roteador_callback_menu))

    # 5. MENSAGENS DE TEXTO (Sempre por último para não bloquear os botões)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, tratar_menu_interativo))

    # Inicia o bot
    app.run_polling()

if __name__ == "__main__":
    main()