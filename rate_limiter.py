import time
from collections import defaultdict
from telegram import Update
from telegram.ext import ContextTypes

# Dicionário em memória para rastrear as requisições: {user_id: [timestamps]}
_controle_acessos = defaultdict(list)

def rate_limit(max_mensagens: int = 5, janela_segundos: int = 60):
    """
    Decorator de Rate Limiting (Antispam).
    Limita o usuário a um número máximo de interações por janela de tempo.
    """
    def decorator(func):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            if not update.effective_user:
                return await func(update, context, *args, **kwargs)
            
            user_id = update.effective_user.id
            agora = time.time()
            
            # Filtra apenas os timestamps dentro da janela de tempo atual (últimos 60 segundos)
            timestamps = _controle_acessos[user_id]
            _controle_acessos[user_id] = [t for t in timestamps if agora - t < janela_segundos]
            
            # Verifica se o usuário excedeu o limite
            if len(_controle_acessos[user_id]) >= max_mensagens:
                if update.message:
                    await update.message.reply_text(
                        "⚠️ Você está enviando mensagens muito rápido. Aguarde alguns instantes."
                    )
                return
            
            # Registra o acesso atual e prossegue com a função original
            _controle_acessos[user_id].append(agora)
            return await func(update, context, *args, **kwargs)
            
        return wrapper
    return decorator