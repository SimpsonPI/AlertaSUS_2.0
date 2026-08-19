from telegram import KeyboardButton, ReplyKeyboardMarkup


def obter_menu_interativo_teclado():
    """Cria botões com o texto visual amigável, mas que disparam comandos nativos (/comando)."""
    teclado = [
        [KeyboardButton("/iniciar")],
        [KeyboardButton("/verificar_todos"), KeyboardButton("/verificar_especifico")],
        [KeyboardButton("/cadastrar_nova"), KeyboardButton("/corrigir")],
        [KeyboardButton("/planos"), KeyboardButton("/excluir")],
        [KeyboardButton("/privacidade"), KeyboardButton("/ajuda")],
    ]
    return ReplyKeyboardMarkup(
        teclado, resize_keyboard=True, persistent=True
    )