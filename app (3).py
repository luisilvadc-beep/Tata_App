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

# --- CSS Customizado ---
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stButton>button {
        width: 100%; border-radius: 12px; height: 3em;
        background: linear-gradient(90deg, #ff4b2b 0%, #ff416c 100%);
        color: white; font-weight: bold; border: none;
    }
    .card {
        background: white; padding: 20px; border-radius: 15px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05); margin-bottom: 20px; border: 1px solid #eee;
    }
    .shopee-orange { color: #ee4d2d; font-weight: bold; }
    .price-tag { font-size: 1.2em; color: #ee4d2d; font-weight: 800; }
    .discount-badge {
        background-color: #fff5f5; color: #ff4b2b; padding: 2px 8px;
        border-radius: 4px; font-size: 0.8em; font-weight: bold; border: 1px solid #ff4b2b;
    }
    .ai-badge {
        font-size: 0.7em; background: #e1e1e1; padding: 2px 5px; border-radius: 3px; color: #555;
    }
    .error-log {
        font-size: 0.8em; color: #d9534f; background: #fdf7f7; padding: 10px; border-radius: 5px; margin-top: 10px;
    }
    </style>
""", unsafe_allow_html=True)

# --- Credenciais ---
SHOPEE_APP_ID = st.secrets.get("SHOPEE_APP_ID")
SHOPEE_APP_SECRET = st.secrets.get("SHOPEE_APP_SECRET")
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY")
GROQ_API_KEY = st.secrets.get("GROQ_API_KEY")

if not SHOPEE_APP_ID or not SHOPEE_APP_SECRET:
    st.error("⚠️ Credenciais Shopee ausentes nos Secrets.")
    st.stop()

SHOPEE_API_URL = "https://open-api.affiliate.shopee.com.br/graphql"

# --- Inicialização ---
if 'seen_ids' not in st.session_state: st.session_state.seen_ids = set()
if 'history' not in st.session_state: st.session_state.history = []
if 'last_errors' not in st.session_state: st.session_state.last_errors = []

# --- Funções Shopee ---
def shopee_signature(payload_str):
    timestamp = str(int(time.time()))
    raw = f"{SHOPEE_APP_ID}{timestamp}{payload_str}{SHOPEE_APP_SECRET}"
    return timestamp, hashlib.sha256(raw.encode("utf-8")).hexdigest()

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
        return r.json().get("data")
    except: return None

def search_products(keyword, limit=50):
    query = f"""{{ productOfferV2(keyword: "{keyword}", listType: 1, sortType: 5, page: 1, limit: {limit}) {{ nodes {{ itemId productName offerLink priceMin priceDiscountRate commissionRate sellerCommissionRate shopName }} }} }}"""
    result = shopee_query(query)
    return result["productOfferV2"]["nodes"] if result else []

def classify_origin(p_name, s_name):
    terms = ['china', 'internacional', 'cross-border', 'envio internacional', 'importado', 'ltd', 'shenzhen', 'guangzhou']
    return "IMPORTADO" if any(t in (p_name + s_name).lower() for t in terms) else "NACIONAL"

def filter_and_pick(products, count, origin_filter, min_disc, min_comm):
    candidates = []
    for p in products:
        if p["itemId"] in st.session_state.seen_ids: continue
        if float(p.get("priceDiscountRate") or 0) < min_disc or float(p.get("commissionRate") or 0) < min_comm: continue
        origin = classify_origin(p['productName'], p['shopName'])
        if origin_filter != "TODAS" and origin != origin_filter: continue
        p['origin'] = origin
        candidates.append(p)
    random.shuffle(candidates)
    selected = candidates[:count]
    for s in selected: st.session_state.seen_ids.add(s["itemId"])
    return selected

# --- Funções IA e Fallback ---
def format_price(price):
    try:
        val = float(price)
        return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return str(price)

def generate_local_text(p, tom):
    """Gerador de emergência sem IA refinado"""
    emojis = ["🔥", "✨", "😱", "🛍️", "✅", "🚀", "💎"]
    frases = [
        "Olha essa oferta imperdível!",
        "Menor preço do dia!",
        "Acabou de baixar o preço!",
        "Dica de economia pra você!",
        "Essa você não pode perder!",
        "Corre que vai acabar rápido!",
        "Oportunidade única na Shopee!"
    ]
    emoji = random.choice(emojis)
    frase = random.choice(frases)
    # Pega o nome mais completo, limitando a 80 caracteres para não ficar gigante mas não cortar demais
    name = p['productName'].strip()
    if len(name) > 85: name = name[:82] + "..."
    
    disc = int(float(p['priceDiscountRate']))
    price = format_price(p['priceMin'])
    link = p['offerLink']
    
    return f"{emoji} {frase}\n\n✨ {name}\n\n❌ {disc}% OFF ❌\n💰 R$ {price}\n\n🔗 {link}"

def call_groq(prompt):
    if not GROQ_API_KEY: return None, "Chave Groq ausente"
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0.8
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        if r.ok:
            content = r.json()['choices'][0]['message']['content']
            return json.loads(content).get("results", []), "Groq"
        return None, f"Groq Erro {r.status_code}"
    except: return None, "Groq Timeout/Erro"

def call_gemini(prompt):
    if not GEMINI_API_KEY: return None, "Chave Gemini ausente"
    endpoints = [
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent",
        "https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent"
    ]
    for url_base in endpoints:
        try:
            url = f"{url_base}?key={GEMINI_API_KEY}"
            payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"response_mime_type": "application/json"}}
            r = requests.post(url, json=payload, timeout=20)
            if r.ok:
                content = r.json()['candidates'][0]['content']['parts'][0]['text']
                return json.loads(content).get("results", []), "Gemini"
        except: continue
    return None, "Gemini falhou"

def generate_texts(products, tom_texto):
    if not products: return [], "Nenhuma"
    prompt = f"Você é um copywriter Shopee. Tom: {tom_texto}. Responda APENAS JSON: {{\"results\": [\"texto1\", ...]}}. Use \\n para quebras. Formato: {{emoji}} {{frase}}\\n\\n✨ {{nome}}\\n\\n❌ {{desconto}}% OFF ❌\\n💰 R$ {{preço}}\\n\\n🔗 {{link}}\n\nProdutos:\n"
    for idx, p in enumerate(products, 1):
        prompt += f"{idx}. {p['productName'][:60]} | R${p['priceMin']} | {int(float(p['priceDiscountRate']))}% OFF | {p['offerLink']}\n"

    st.session_state.last_errors = []
    
    # Tenta Groq
    res, err1 = call_groq(prompt)
    if not res: 
        st.session_state.last_errors.append(err1)
        # Tenta Gemini
        res, err2 = call_gemini(prompt)
        if not res: 
            st.session_state.last_errors.append(err2)
            # Fallback Local
            return [generate_local_text(p, tom_texto) for p in products], "Local (Segurança)"
    
    texts, provider = res, "IA"
    while len(texts) < len(products): texts.append(generate_local_text(products[len(texts)], tom_texto))
    return texts[:len(products)], provider

# --- UI ---
st.markdown("<h1 style='text-align: center;'>🛍️ Shopee Fácil</h1>", unsafe_allow_html=True)

with st.container():
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    c1, c2 = st.columns([2, 1])
    num = c1.slider("Ofertas", 1, 20, 8)
    orig = c2.selectbox("Origem", ["TODAS", "NACIONAL", "IMPORTADO"])
    
    with st.expander("⚙️ Configurações"):
        kws = st.text_area("Categorias:", "cozinha\ndecoração\nutilidades", height=70)
        tom = st.text_input("Tom:", "Animado e focado em economia")
        if st.session_state.last_errors:
            st.markdown("<div class='error-log'><b>Logs de Erro:</b><br>" + "<br>".join(st.session_state.last_errors) + "</div>", unsafe_allow_html=True)

    if st.button("🚀 Gerar Ofertas"):
        keywords = [k.strip() for k in kws.split('\n') if k.strip()]
        if keywords:
            with st.status("Processando...", expanded=True) as status:
                all_p = []
                for kw in keywords: all_p.extend(search_products(kw))
                sel = filter_and_pick(all_p, num, orig, 0.2, 0.08)
                
                if sel:
                    txts, prov = generate_texts(sel, tom)
                    for i, p in enumerate(sel):
                        st.session_state.history.insert(0, {
                            "name": p['productName'], "price": p['priceMin'], 
                            "discount": int(float(p['priceDiscountRate'])), 
                            "link": p['offerLink'], "text": txts[i], 
                            "origin": p['origin'], "provider": prov
                        })
                    status.update(label=f"Pronto via {prov}!", state="complete", expanded=False)
                else: status.update(label="Nada novo.", state="error")
    st.markdown("</div>", unsafe_allow_html=True)

if st.session_state.history:
    st.subheader("✨ Últimas Ofertas")
    if st.button("🗑️ Limpar"):
        st.session_state.history = []; st.session_state.seen_ids = set(); st.rerun()
    for item in st.session_state.history:
        with st.container():
            st.markdown(f"""<div class='card'><div style='display: flex; justify-content: space-between;'><div><div class='shopee-orange'>{item['name'][:60]}...</div><div style='margin-top: 8px;'><span class='price-tag'>R$ {format_price(item['price'])}</span> <span style='color: #888; font-size: 0.8em;'>• {item['origin']}</span> <span class='ai-badge'>{item['provider']}</span></div></div><div class='discount-badge'>{item['discount']}% OFF</div></div></div>""", unsafe_allow_html=True)
            st.code(item['text'], language="text")
else: st.info("Gere ofertas acima! ✨")
