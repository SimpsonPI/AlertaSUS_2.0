import asyncio
from telegram import Bot

# Token atribuído diretamente à variável
TOKEN = "8988706536:AAEL-v0-wG-Qad6-igxs4kiTa3c93icg9I0"


async def limpar_comandos():
    bot = Bot(token=TOKEN)
    sucesso = await bot.delete_my_commands()

    if sucesso:
        print("✅ Menu de comandos removido com sucesso no Telegram!")
    else:
        print("❌ Falha ao remover o menu de comandos.")


if __name__ == "__main__":
    asyncio.run(limpar_comandos())