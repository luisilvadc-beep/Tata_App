import streamlit as st
import time
import json
import hashlib
import requests
import random
import re
import html

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
    </style>
""", unsafe_allow_html=True)

# --- Credenciais (só Shopee — sem IA nessa versão) ---
SHOPEE_APP_ID = st.secrets.get("SHOPEE_APP_ID")
SHOPEE_APP_SECRET = st.secrets.get("SHOPEE_APP_SECRET")

if not SHOPEE_APP_ID or not SHOPEE_APP_SECRET:
    st.error("⚠️ Credenciais Shopee ausentes nos Secrets.")
    st.stop()

SHOPEE_API_URL = "https://open-api.affiliate.shopee.com.br/graphql"

# --- Inicialização ---
if 'seen_ids' not in st.session_state: st.session_state.seen_ids = set()
if 'history' not in st.session_state: st.session_state.history = []

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
    except Exception:
        return None

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
        if p["itemId"] in st.session_state.seen_ids:
            continue
        if float(p.get("priceDiscountRate") or 0) < min_disc or float(p.get("commissionRate") or 0) < min_comm:
            continue
        origin = classify_origin(p['productName'], p['shopName'])
        if origin_filter != "TODAS" and origin != origin_filter:
            continue
        p['origin'] = origin
        candidates.append(p)
    random.shuffle(candidates)
    selected = candidates[:count]
    for s in selected:
        st.session_state.seen_ids.add(s["itemId"])
    return selected

# --- Tratamento de texto (sem IA, mas robusto pra qualquer caractere) ---
def clean_product_name(raw_name):
    """
    Limpa o nome do produto preservando acentos, emojis e caracteres válidos,
    mas removendo lixo comum de título de e-commerce (HTML entities, símbolos
    de controle, espaços duplicados, barras verticais soltas).
    """
    if not raw_name:
        return "Produto"

    name = raw_name.strip()

    # Decodifica entidades HTML tipo &amp; &quot; que às vezes vêm da API
    name = html.unescape(name)

    # Remove caracteres de controle invisíveis (mas mantém emojis e acentos)
    name = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', name)

    # Normaliza espaços múltiplos, tabs e quebras de linha internas
    name = re.sub(r'\s+', ' ', name)

    # Remove barras verticais e colchetes soltos que a Shopee às vezes deixa
    # (ex: "Produto | | Frete Grátis []")
    name = re.sub(r'\s*\|\s*\|\s*', ' | ', name)
    name = name.strip(' |[]')

    return name.strip()


def truncate_smart(text, max_len):
    """Corta no limite de palavra mais próximo, sem partir palavra ao meio."""
    if len(text) <= max_len:
        return text
    cut = text[:max_len].rsplit(' ', 1)[0]
    return cut.rstrip('.,;:!?-') + "..."


def format_price(price):
    try:
        val = float(price)
        return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(price)


# Frases variadas por "clima" — dá mais variedade que uma lista única fixa
FRASES_POR_TOM = {
    "padrao": [
        "Olha essa oferta imperdível!",
        "Menor preço do dia!",
        "Acabou de baixar o preço!",
        "Dica de economia pra você!",
        "Essa você não pode perder!",
        "Corre que vai acabar rápido!",
        "Oportunidade única na Shopee!",
        "Separei essa achado pra você!",
        "Vale muito a pena conferir!",
        "Preço bom desses não dura!",
    ],
    "urgente": [
        "ÚLTIMAS UNIDADES, corre!",
        "Só hoje com esse preço!",
        "Vai acabar rapidinho, garante já!",
        "Estoque limitado, aproveita agora!",
    ],
    "economico": [
        "Economia de verdade aqui!",
        "Seu bolso vai agradecer!",
        "Preço que cabe no orçamento!",
        "Compra inteligente do dia!",
    ],
}

EMOJIS = ["🔥", "✨", "😱", "🛍️", "✅", "🚀", "💎", "🎯", "💥", "🌟"]


def pick_frase(tom_texto: str) -> str:
    tom_lower = (tom_texto or "").lower()
    if any(w in tom_lower for w in ["urgen", "corre", "rápido", "acaba"]):
        pool = FRASES_POR_TOM["urgente"]
    elif any(w in tom_lower for w in ["econom", "barato", "orçamento"]):
        pool = FRASES_POR_TOM["economico"]
    else:
        pool = FRASES_POR_TOM["padrao"]
    return random.choice(pool)


def generate_local_text(p, tom):
    """
    Gerador 100% local (sem IA). Suporta nomes de produto com qualquer
    caractere Unicode (acentos, emojis, símbolos), sem cortar no meio
    de uma palavra e sem impor um limite artificialmente curto.
    """
    emoji = random.choice(EMOJIS)
    frase = pick_frase(tom)

    name = clean_product_name(p.get('productName', ''))
    # Limite generoso — WhatsApp aceita textos longos sem problema,
    # então só cortamos nomes realmente extremos (>160 chars)
    name = truncate_smart(name, 160)

    try:
        disc = int(float(p.get('priceDiscountRate', 0) or 0))
    except (ValueError, TypeError):
        disc = 0

    price = format_price(p.get('priceMin', 0))
    link = p.get('offerLink', '')

    texto = f"{emoji} {frase}\n\n✨ {name}\n\n❌ {disc}% OFF ❌\n💰 R$ {price}\n\n🔗 {link}"

    # Garantia final: o texto inteiro passa por um encode/decode UTF-8
    # pra garantir que nenhum caractere problemático quebre a exibição
    # ou o envio posterior (WhatsApp, clipboard, etc.)
    texto = texto.encode('utf-8', errors='ignore').decode('utf-8')

    return texto


def generate_texts(products, tom_texto):
    """Gera todos os textos localmente — sem chamadas de API externas."""
    return [generate_local_text(p, tom_texto) for p in products], "Local (sem IA)"


# --- UI ---
st.markdown("<h1 style='text-align: center;'>🛍️ Shopee Fácil</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #666;'>Curadoria automática, texto pronto para WhatsApp — sem depender de IA externa.</p>", unsafe_allow_html=True)

with st.container():
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    c1, c2 = st.columns([2, 1])
    num = c1.slider("Ofertas", 1, 20, 8)
    orig = c2.selectbox("Origem", ["TODAS", "NACIONAL", "IMPORTADO"])

    with st.expander("⚙️ Configurações"):
        kws = st.text_area("Categorias:", "cozinha\ndecoração\nutilidades", height=70)
        tom = st.text_input("Tom:", "Animado e focado em economia")
        st.caption("Dica: palavras como 'urgente' ou 'econômico' no tom mudam o estilo das frases.")

    if st.button("🚀 Gerar Ofertas"):
        keywords = [k.strip() for k in kws.split('\n') if k.strip()]
        if keywords:
            with st.status("Processando...", expanded=True) as status:
                all_p = []
                for kw in keywords:
                    all_p.extend(search_products(kw))
                sel = filter_and_pick(all_p, num, orig, 0.2, 0.08)

                if sel:
                    txts, prov = generate_texts(sel, tom)
                    for i, p in enumerate(sel):
                        st.session_state.history.insert(0, {
                            "name": clean_product_name(p['productName']),
                            "price": p['priceMin'],
                            "discount": int(float(p['priceDiscountRate'])),
                            "link": p['offerLink'],
                            "text": txts[i],
                            "origin": p['origin'],
                            "provider": prov
                        })
                    status.update(label=f"Pronto via {prov}!", state="complete", expanded=False)
                else:
                    status.update(label="Nada novo.", state="error")
    st.markdown("</div>", unsafe_allow_html=True)

if st.session_state.history:
    st.subheader("✨ Últimas Ofertas")
    if st.button("🗑️ Limpar"):
        st.session_state.history = []
        st.session_state.seen_ids = set()
        st.rerun()
    for item in st.session_state.history:
        with st.container():
            display_name = truncate_smart(item['name'], 140)
            st.markdown(
                f"""<div class='card'><div style='display: flex; justify-content: space-between;'>
                <div><div class='shopee-orange'>{display_name}</div>
                <div style='margin-top: 8px;'>
                <span class='price-tag'>R$ {format_price(item['price'])}</span>
                <span style='color: #888; font-size: 0.8em;'>• {item['origin']}</span>
                <span class='ai-badge'>{item['provider']}</span></div></div>
                <div class='discount-badge'>{item['discount']}% OFF</div></div></div>""",
                unsafe_allow_html=True
            )
            st.code(item['text'], language="text")
else:
    st.info("Gere ofertas acima! ✨")
    
