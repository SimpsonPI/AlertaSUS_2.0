import httpx
from bs4 import BeautifulSoup

# Número da regulação cadastrada para teste
NUMERO_REG = "108229301"

URL_BUSCA = "https://agendamentos.sus.fms.pmt.pi.gov.br/detail_scheduling/index"
params = {"number_id": NUMERO_REG}

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

print(f"🔍 Testando consulta para a regulação {NUMERO_REG}...", flush=True)

try:
    with httpx.Client(verify=False, follow_redirects=True, timeout=15.0) as client:
        resposta = client.get(URL_BUSCA, params=params, headers=headers)
        soup = BeautifulSoup(resposta.text, "html.parser")
        
        print(f"✅ Status HTTP: {resposta.status_code}\n")
        
        print("--- Conteúdo Relevante Encontrado ---")
        # Extrai textos de tabelas, parágrafos e divs
        elementos = soup.find_all(['td', 'th', 'p', 'span', 'div', 'h1', 'h2', 'h3', 'h4'])
        textos = [e.get_text(strip=True) for e in elementos if e.get_text(strip=True)]
        
        # Exibe as primeiras 30 linhas de texto encontradas
        for i, texto in enumerate(textos[:30], 1):
            print(f"{i}. {texto}")

except Exception as e:
    print(f"❌ Erro na consulta: {e}")