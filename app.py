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
            st.error(f"Erro Shopee API: {data['errors']}")
            return None
        return data.get("data")
    except Exception as e:
        st.error(f"Erro de conexão com Shopee: {e}")
        return None

def search_products(keyword, limit=50):
    # Aumentamos o limite para ter mais opções e filtrar dinamicamente
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
    """Heurística simples para classificar origem se não houver API direta"""
    china_terms = ['china', 'internacional', 'cross-border', 'envio internacional', 'importado']
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
        
        # Filtros básicos
        if discount < min_discount or commission < min_comm:
            continue
            
        # Filtro de Origem (Heurística)
        origin = classify_origin(p['productName'], p['shopName'])
        if origin_filter != "TODAS":
            if origin_filter == "NACIONAL" and origin != "NACIONAL":
                continue
            if origin_filter == "IMPORTADO" and origin != "IMPORTADO":
                continue
        
        p['origin'] = origin
        candidates.append(p)
    
    # Embaralhar para ser dinâmico
    random.shuffle(candidates)
    
    selected = candidates[:target_count]
    for s in selected:
        st.session_state.seen_ids.add(s["itemId"])
    
    return selected

# --- Funções IA (Gemini) ---
def sanitize_text(text):
    if not text: return ""
    return re.sub(r'[\x00-\x1F\x7F]', '', text).replace('"', "'").replace('\n', ' ').strip()

def generate_texts_ai(products, tom_texto):
    if not products:
        return []
    
    SYSTEM_PROMPT = f"""Você é um copywriter especialista em Shopee.
Crie posts curtos e persuasivos para WhatsApp.
Tom: {tom_texto}.

Para cada produto, retorne um objeto JSON no array 'results'.
Use \\n para quebras de linha.
Formato do texto:
{{emoji}} {{frase criativa}}\\n\\n✨ {{nome do produto}}\\n\\n❌ Com {{desconto}}% OFF ❌\\n💰 Por apenas R${{preço}}\\n\\n🔗 Link: {{link}}

Retorne APENAS o JSON: {{"results": ["texto1", "texto2"]}}"""

    product_list = []
    for i, p in enumerate(products, 1):
        product_list.append(f"{i}. {sanitize_text(p['productName'])} | R${p['priceMin']} | {int(float(p['priceDiscountRate']))}% OFF | {p['offerLink']}")
    
    user_msg = "\n".join(product_list)
    
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
        "temperature": 0.8 # Um pouco de aleatoriedade
    }
    
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        r.raise_for_status()
        res_json = r.json()
        raw_content = res_json["choices"][0]["message"]["content"]
        
        # Limpeza robusta de JSON
        match = re.search(r'\{.*\}', raw_content, re.DOTALL)
        if match:
            clean_json = match.group(0)
            data = json.loads(clean_json)
            return [t.replace('\\n', '\n') for t in data.get("results", [])]
        else:
            st.error("IA não retornou um formato JSON válido.")
            return []
    except Exception as e:
        st.error(f"Erro na IA: {e}")
        return []

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
            with st.status("Buscando ofertas imperdíveis...", expanded=True) as status:
                all_found = []
                for kw in keywords:
                    status.write(f"Pesquisando: {kw}")
                    prods = search_products(kw)
                    all_found.extend(prods)
                
                selected = filter_and_pick(all_found, num_offers, origin, min_disc, min_comm)
                
                if not selected:
                    status.update(label="Nenhum produto novo encontrado com esses filtros.", state="error")
                else:
                    status.write("Gerando textos criativos...")
                    textos = generate_texts_ai(selected, tom_input)
                    
                    # Salvar no histórico
                    new_entries = []
                    for i, p in enumerate(selected):
                        txt = textos[i] if i < len(textos) else "Erro ao gerar texto."
                        new_entries.append({
                            "name": p['productName'],
                            "price": p['priceMin'],
                            "discount": int(float(p['priceDiscountRate'])),
                            "link": p['offerLink'],
                            "text": txt,
                            "origin": p['origin']
                        })
                    
                    st.session_state.history = new_entries + st.session_state.history
                    status.update(label=f"Sucesso! {len(selected)} ofertas geradas.", state="complete", expanded=False)

    st.markdown("</div>", unsafe_allow_html=True)

# Exibição do Histórico/Resultados
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
                    <div style='display: flex; justify-content: space-between;'>
                        <span class='shopee-orange'>{item['name'][:50]}...</span>
                        <span class='discount-badge'>{item['discount']}% OFF</span>
                    </div>
                    <div style='margin-top: 10px;'>
                        <span class='price-tag'>R$ {item['price']}</span> 
                        <span style='color: #888; font-size: 0.8em;'>• {item['origin']}</span>
                    </div>
                </div>
            """, unsafe_allow_html=True)
            
            # Área de texto para copiar
            st.code(item['text'], language="text")
            st.markdown("---")
else:
    st.info("Nada por aqui ainda. Ajuste os filtros e clique em **Gerar Novas Ofertas**! ✨")
    
