import httpx
from bs4 import BeautifulSoup

URL_FMS = "https://agendamentos.sus.fms.pmt.pi.gov.br/"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

print("🔍 Inspecionando o formulário do portal da FMS...", flush=True)

try:
    with httpx.Client(verify=False, follow_redirects=True, timeout=10.0) as client:
        resposta = client.get(URL_FMS, headers=headers)
        soup = BeautifulSoup(resposta.text, "html.parser")
        
        form = soup.find("form")
        if form:
            print(f"✅ Formulário encontrado!")
            print(f"📌 Ação (action): {form.get('action')}")
            print(f"📌 Método (method): {form.get('method', 'GET')}\n")
            
            campos = form.find_all(["input", "button", "select"])
            print("--- Campos de entrada encontrados ---")
            for campo in campos:
                nome = campo.get("name")
                tipo = campo.get("type", "desconhecido")
                placeholder = campo.get("placeholder", "")
                print(f" • Nome: '{nome}' | Tipo: '{tipo}' | Texto ajuda: '{placeholder}'")
        else:
            print("⚠️ Nenhum formulário HTML tradicional encontrado (a busca pode ser carregada por JavaScript/API).")

except Exception as e:
    print(f"❌ Erro ao acessar o portal: {e}")