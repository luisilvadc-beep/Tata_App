import streamlit as st
import time
import json
import hashlib
import requests
from groq import Groq

# --- Configuração da Página ---
st.set_page_config(page_title="Gerador de Ofertas Shopee", page_icon="🛍️", layout="centered")

# --- Credenciais (via st.secrets no Streamlit Cloud) ---
try:
    SHOPEE_APP_ID = st.secrets["SHOPEE_APP_ID"]
    SHOPEE_APP_SECRET = st.secrets["SHOPEE_APP_SECRET"]
    GROQ_API_KEY = st.secrets["GROQ_API_KEY"]
except KeyError:
    st.error("⚠️ Credenciais não configuradas. Adicione-as nos Secrets do Streamlit Cloud.")
    st.stop()

SHOPEE_API_URL = "https://open-api.affiliate.shopee.com.br/graphql"

# --- Configurações Fixas ---
MIN_DISCOUNT = 0.20 # Desconto mínimo real (20%)
MIN_COMMISSION = 0.08
PRODUCTS_PER_KEYWORD = 2

# --- Funções Base ---
def shopee_signature(payload_str):
    timestamp = str(int(time.time()))
    raw = f"{SHOPEE_APP_ID}{timestamp}{payload_str}{SHOPEE_APP_SECRET}"
    signature = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return timestamp, signature

def shopee_query(query):
    payload = {"query": query}
    payload_str = json.dumps(payload, separators=(",", ":"))
    timestamp, signature = shopee_signature(payload_str)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"SHA256 Credential={SHOPEE_APP_ID}, Timestamp={timestamp}, Signature={signature}",
    }
    r = requests.post(SHOPEE_API_URL, data=payload_str, headers=headers, timeout=20)
    r.raise_for_status()
    data = r.json()
    if data.get("errors"):
        raise RuntimeError(f"Erro Shopee API: {data['errors']}")
    return data["data"]

def search_products(keyword, limit=20):
    query = f"""
    {{
      productOfferV2(
        keyword: "{keyword}",
        listType: 1,
        sortType: 5,
        page: 1,
        limit: {limit}
      ) {{
        nodes {{
          itemId
          productName
          offerLink
          priceMin
          priceDiscountRate
          commissionRate
          sellerCommissionRate
          shopName
        }}
      }}
    }}
    """
    result = shopee_query(query)
    return result["productOfferV2"]["nodes"]

def pick_best(products, seen_ids):
    candidates = []
    for p in products:
        if p["itemId"] in seen_ids:
            continue
        discount = float(p.get("priceDiscountRate") or 0)
        commission = float(p.get("commissionRate") or 0)
        seller_comm = float(p.get("sellerCommissionRate") or 0)
        
        if discount >= MIN_DISCOUNT and commission >= MIN_COMMISSION and seller_comm > 0:
            seen_ids.add(p["itemId"])
            candidates.append(p)
            
    candidates.sort(key=lambda p: float(p["commissionRate"]), reverse=True)
    return candidates[:PRODUCTS_PER_KEYWORD]

def build_prompt(products):
    lines = []
    for i, p in enumerate(products, start=1):
        price = p.get("priceMin")
        discount_pct = round(float(p.get("priceDiscountRate", 0)))
        lines.append(
            f"{i}. Produto: {p['productName']} | Preco: R${price} | Desconto: {discount_pct}% | Link: {p['offerLink']}"
        )
    return "\n".join(lines)

def generate_texts(products, tom_texto):
    if not products:
        return []
    
    SYSTEM_PROMPT = f"""Você é especialista em copywriting para ofertas de afiliados da Shopee no WhatsApp.
O tom da mensagem deve ser: {tom_texto}.

Para cada produto, crie um texto EXATAMENTE neste formato, usando \\n para quebras de linha dentro do JSON:

{{emoji}} {{frase criativa de até 10 palavras}}\\n\\n✨ {{nome do produto limpo}}\\n\\n❌ Com {{desconto}}% de desconto ❌\\n💰 Somente R${{preço}}.\\n\\n🔗 COMPRE AQUI 👉🏽 {{link}}

Responda SOMENTE com JSON válido sem markdown:
{{"results": ["texto1", "texto2"]}}
A ordem deve ser a mesma dos produtos recebidos."""

    client = Groq(api_key=GROQ_API_KEY)
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_prompt(products)},
        ],
    )
    cleaned = response.choices[0].message.content.replace("```json", "").replace("```", "").strip()
    return json.loads(cleaned).get("results", [])

# --- Interface de Usuário (UI) ---
st.title("🛍️ Gerador de Ofertas Shopee")
st.write("Busque os melhores produtos e gere os textos para o WhatsApp automaticamente.")

keywords_input = st.text_area("Categorias (uma por linha):", "cozinha\ndecoração casa\nmoda feminina")
tom_input = st.text_input("Tom das frases de abertura (Ex: Animado, Urgente, Foco em economia):", "Animado e focado em economia, como se estivesse contando um segredo para uma amiga")

if st.button("🚀 Buscar e Gerar Textos", use_container_width=True):
    keywords_list = [k.strip() for k in keywords_input.split('\n') if k.strip()]
    
    if not keywords_list:
        st.warning("Por favor, insira pelo menos uma categoria.")
    else:
        all_selected = []
        seen_ids = set()
        
        progress_text = "Buscando produtos na Shopee..."
        my_bar = st.progress(0, text=progress_text)
        
        for idx, keyword in enumerate(keywords_list):
            try:
                products = search_products(keyword)
                best = pick_best(products, seen_ids)
                all_selected.extend(best)
            except Exception as e:
                st.error(f"Erro ao buscar '{keyword}': {e}")
            
            my_bar.progress((idx + 1) / len(keywords_list), text=f"Buscando: {keyword}")
            
        if not all_selected:
            st.warning("⚠️ Nenhum produto passou pelos filtros (Desconto > 20% e Comissão > 8%).")
        else:
            st.info(f"✅ {len(all_selected)} produto(s) encontrado(s)! Gerando textos com IA...")
            
            try:
                textos = generate_texts(all_selected, tom_input)
                st.success("🎉 Ofertas prontas! Só clicar no botão de copiar abaixo de cada uma.")
                
                for i, t in enumerate(textos, 1):
                    texto_formatado = t.replace("\\n", "\n")
                    with st.container(border=True):
                        st.text(texto_formatado)
                        st.code(texto_formatado, language="text")
            except Exception as e:
                st.error(f"❌ Erro na geração de texto: {e}")
