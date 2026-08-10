from handlers_utils import (
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
    TECLADO_MENU,
    TECLADO_CANCELAR,
    TECLADO_CONFIRMACAO,
    AVISO_PRIVADO_HTML
)

from handlers_base import (
    start,
    comando_ajuda,
    cancelar_operacao,
    verificar_se_e_menu_e_executar,
    configurar_menu_comandos,
    executar_varredura_automatica,
    abrir_link_cadastro
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

from handlers_consulta import (
    comando_verificar_todas,
    iniciar_verificar_especifico,
    processar_verificar_especifico
)

from handlers_correcao import (
    iniciar_corrigir,
    selecionar_regulacao_callback,
    selecionar_campo_callback,
    salvar_novo_valor,
    cancelar_corrigir
)

from handlers_exclusao import (
    iniciar_excluir,
    selecionar_regulacao_excluir_callback,
    confirmar_exclusao_callback,
    cancelar_excluir
)