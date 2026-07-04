import streamlit as st
import time
import json
import hashlib
import requests
import random
import re

# --- Configuração da Página ---
st.set_page_config(
    page_title="Shopee Fácil - Gerador de Ofertas",
    page_icon="🛍️",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# --- CSS Customizado para Estilo Lovable ---
st.markdown("""
    <style>
    .main {
        background-color: #f8f9fa;
    }
    .stButton>button {
        width: 100%;
        border-radius: 12px;
        height: 3em;
        background: linear-gradient(90deg, #ff4b2b 0%, #ff416c 100%);
        color: white;
        font-weight: bold;
        border: none;
    }
    .stButton>button:hover {
        background: linear-gradient(90deg, #ff416c 0%, #ff4b2b 100%);
        color: white;
    }
    .card {
        background: white;
        padding: 20px;
        border-radius: 15px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        margin-bottom: 20px;
        border: 1px solid #eee;
    }
    .shopee-orange {
        color: #ee4d2d;
        font-weight: bold;
    }
    .price-tag {
        font-size: 1.2em;
        color: #ee4d2d;
        font-weight: 800;
    }
    .discount-badge {
        background-color: #fff5f5;
        color: #ff4b2b;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.8em;
        font-weight: bold;
        border: 1px solid #ff4b2b;
    }
    </style>
""", unsafe_allow_html=True)

# --- Credenciais ---
try:
    SHOPEE_APP_ID = st.secrets["SHOPEE_APP_ID"]
    SHOPEE_APP_SECRET = st.secrets["SHOPEE_APP_SECRET"]
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except KeyError:
    st.error("⚠️ Credenciais não configuradas. Adicione-as nos Secrets do Streamlit Cloud.")
    st.stop()

SHOPEE_API_URL = "https://open-api.affiliate.shopee.com.br/graphql"

# --- Inicialização do Session State ---
if 'seen_ids' not in st.session_state:
    st.session_state.seen_ids = set()
if 'history' not in st.session_state:
    st.session_state.history = []

# --- Funções Shopee ---
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
    try:
        r = requests.post(SHOPEE_API_URL, data=payload_str, headers=headers, timeout=20)
        r.raise_for_status()
        data = r.json()
        if data.get("errors"):
            return None
        return data.get("data")
    except Exception:
        return None

def search_products(keyword, limit=50):
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
    if result and "productOfferV2" in result:
        return result["productOfferV2"]["nodes"]
    return []

def classify_origin(product_name, shop_name):
    china_terms = ['china', 'internacional', 'cross-border', 'envio internacional', 'importado', 'ltd', 'shenzhen', 'guangzhou']
    text = f"{product_name} {shop_name}".lower()
    if any(term in text for term in china_terms):
        return "IMPORTADO"
    return "NACIONAL"

def filter_and_pick(products, target_count, origin_filter, min_discount, min_comm):
    candidates = []
    for p in products:
        if p["itemId"] in st.session_state.seen_ids:
            continue
            
        discount = float(p.get("priceDiscountRate") or 0)
        commission = float(p.get("commissionRate") or 0)
        
        if discount < min_discount or commission < min_comm:
            continue
            
        origin = classify_origin(p['productName'], p['shopName'])
        if origin_filter != "TODAS":
            if origin_filter == "NACIONAL" and origin != "NACIONAL":
                continue
            if origin_filter == "IMPORTADO" and origin != "IMPORTADO":
                continue
        
        p['origin'] = origin
        candidates.append(p)
    
    random.shuffle(candidates)
    selected = candidates[:target_count]
    for s in selected:
        st.session_state.seen_ids.add(s["itemId"])
    
    return selected

# --- Funções IA (Gemini) ---
def sanitize_text(text):
    if not text: return ""
    # Remove caracteres de controle e sanitiza aspas
    text = re.sub(r'[\x00-\x1F\x7F]', '', text)
    return text.replace('"', "'").replace('\n', ' ').strip()

def generate_texts_in_batches(products, tom_texto, batch_size=4):
    """Gera textos em lotes menores para evitar erros de limite ou falhas no JSON da IA"""
    all_texts = []
    
    for i in range(0, len(products), batch_size):
        batch = products[i:i + batch_size]
        
        SYSTEM_PROMPT = f"""Você é um copywriter especialista em Shopee para WhatsApp.
Tom: {tom_texto}.
Crie um post curto e chamativo para cada produto abaixo.

Regras:
1. Use emojis.
2. Formato: {{emoji}} {{frase}}\\n\\n✨ {{nome}}\\n\\n❌ {{desconto}}% OFF ❌\\n💰 R$ {{preço}}\\n\\n🔗 {{link}}
3. Responda APENAS com um JSON no formato: {{"results": ["texto1", "texto2", ...]}}
4. Use \\n para quebras de linha dentro das strings."""

        product_data = []
        for idx, p in enumerate(batch, 1):
            name = sanitize_text(p['productName'])
            price = p['priceMin']
            disc = int(float(p['priceDiscountRate']))
            link = p['offerLink']
            product_data.append(f"Prod {idx}: {name} | R${price} | {disc}% OFF | {link}")
        
        user_msg = "\n".join(product_data)
        
        url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GEMINI_API_KEY}"
        }
        payload = {
            "model": "gemini-1.5-flash",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg}
            ],
            "temperature": 0.9
        }
        
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=40)
            if r.ok:
                res_json = r.json()
                content = res_json["choices"][0]["message"]["content"]
                
                # Extração robusta do JSON
                match = re.search(r'\{.*\}', content, re.DOTALL)
                if match:
                    data = json.loads(match.group(0))
                    batch_results = [t.replace('\\n', '\n') for t in data.get("results", [])]
                    # Garantir que temos o mesmo número de textos que produtos no lote
                    while len(batch_results) < len(batch):
                        batch_results.append("⚠️ Erro ao gerar este texto específico.")
                    all_texts.extend(batch_results[:len(batch)])
                else:
                    all_texts.extend(["⚠️ Erro: IA não retornou JSON."] * len(batch))
            else:
                all_texts.extend([f"⚠️ Erro HTTP {r.status_code}"] * len(batch))
        except Exception as e:
            all_texts.extend([f"⚠️ Erro técnico: {str(e)[:30]}"] * len(batch))
            
    return all_texts

# --- UI Principal ---
st.markdown("<h1 style='text-align: center;'>🛍️ Shopee Fácil</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #666;'>Curadoria automática, texto pronto para WhatsApp.</p>", unsafe_allow_html=True)

# Layout Estilo Lovable (Cards)
with st.container():
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    
    col1, col2 = st.columns([2, 1])
    with col1:
        num_offers = st.slider("Quantas ofertas gerar?", 1, 30, 12)
    with col2:
        origin = st.selectbox("Origem", ["TODAS", "NACIONAL", "IMPORTADO"])
    
    with st.expander("⚙️ Ajustar Filtros e Categorias"):
        keywords_input = st.text_area("Categorias (uma por linha):", "cozinha\ndecoração\nutilidades\nmoda feminina", height=100)
        tom_input = st.text_input("Tom da voz:", "Animado e focado em economia")
        
        c1, c2 = st.columns(2)
        min_disc = c1.number_input("Desconto Mínimo (%)", 0, 100, 20) / 100
        min_comm = c2.number_input("Comissão Mínima (%)", 0, 100, 8) / 100

    if st.button("🚀 Gerar Novas Ofertas"):
        keywords = [k.strip() for k in keywords_input.split('\n') if k.strip()]
        if not keywords:
            st.warning("Insira pelo menos uma categoria.")
        else:
            with st.status("Processando...", expanded=True) as status:
                all_found = []
                for kw in keywords:
                    status.write(f"Buscando produtos: {kw}")
                    prods = search_products(kw)
                    all_found.extend(prods)
                
                selected = filter_and_pick(all_found, num_offers, origin, min_disc, min_comm)
                
                if not selected:
                    status.update(label="Nenhum produto novo encontrado.", state="error")
                else:
                    status.write(f"Gerando textos para {len(selected)} produtos...")
                    textos = generate_texts_in_batches(selected, tom_input)
                    
                    # Salvar no histórico
                    new_entries = []
                    for i, p in enumerate(selected):
                        txt = textos[i] if i < len(textos) else "⚠️ Erro na geração."
                        new_entries.append({
                            "name": p['productName'],
                            "price": p['priceMin'],
                            "discount": int(float(p['priceDiscountRate'])),
                            "link": p['offerLink'],
                            "text": txt,
                            "origin": p['origin']
                        })
                    
                    st.session_state.history = new_entries + st.session_state.history
                    status.update(label=f"Pronto! {len(selected)} ofertas adicionadas.", state="complete", expanded=False)

    st.markdown("</div>", unsafe_allow_html=True)

# Exibição do Histórico
if st.session_state.history:
    st.subheader(f"✨ Últimas Ofertas ({len(st.session_state.history)})")
    
    if st.button("🗑️ Limpar Histórico"):
        st.session_state.history = []
        st.session_state.seen_ids = set()
        st.rerun()

    for item in st.session_state.history:
        with st.container():
            st.markdown(f"""
                <div class='card'>
                    <div style='display: flex; justify-content: space-between; align-items: start;'>
                        <div style='flex: 1; padding-right: 10px;'>
                            <div class='shopee-orange' style='font-size: 1.1em;'>{item['name'][:60]}...</div>
                            <div style='margin-top: 8px;'>
                                <span class='price-tag'>R$ {item['price']}</span> 
                                <span style='color: #888; font-size: 0.8em; margin-left: 10px;'>• {item['origin']}</span>
                            </div>
                        </div>
                        <div class='discount-badge' style='white-space: nowrap;'>{item['discount']}% OFF</div>
                    </div>
                </div>
            """, unsafe_allow_html=True)
            
            # Área de texto para copiar
            st.code(item['text'], language="text")
            st.markdown("<div style='margin-bottom: 30px;'></div>", unsafe_allow_html=True)
else:
    st.info("Nada por aqui ainda. Ajuste os filtros e clique em **Gerar Novas Ofertas**! ✨")
    
