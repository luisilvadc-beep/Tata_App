import google.generativeai as genai
import json
import os
from typing import List, Dict

class GeminiProcessor:
    """Integração com Gemini API (Camada Gratuita)"""
    
    SYSTEM_PROMPT = """Você é especialista em copywriting para ofertas de afiliados da Shopee no WhatsApp.

Para cada produto, crie um texto EXATAMENTE neste formato, usando \\n para quebras de linha dentro do JSON:

{emoji} {frase criativa de até 10 palavras}\\n\\n✨ {nome do produto limpo}\\n\\n❌ Com {desconto}% de desconto ❌\\n💰 Somente R${preço}.\\n\\n🔗 COMPRE AQUI 👉🏽 {link}

Responda SOMENTE com JSON válido sem markdown:
{"results": ["texto1", "texto2"]}
A ordem deve ser a mesma dos produtos recebidos."""
    
    def __init__(self):
        # A chave será puxada dos Secrets do Streamlit
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY não encontrada.")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-1.5-flash')
    
    def _sanitize_string(self, text: str) -> str:
        return text.replace('"', "'").replace("\n", " ").replace("\r", " ").replace("\t", " ").strip()
    
    def _build_prompt(self, products: List[Dict]) -> str:
        lines = []
        for i, p in enumerate(products, start=1):
            price = p.get("priceMin")
            discount_pct = round(float(p.get("priceDiscountRate", 0)))
            product_name = self._sanitize_string(p.get("productName", ""))
            shop_name = self._sanitize_string(p.get("shopName", ""))
            
            lines.append(
                f"{i}. Produto: {product_name} | Vendedor: {shop_name} | Preco: R${price} | Desconto: {discount_pct}% | Link: {p.get('offerLink')}"
            )
        return "\n".join(lines)
    
    def generate_texts(self, products: List[Dict]) -> List[str]:
        if not products:
            return []
        
        user_msg = self._build_prompt(products)
        prompt_completo = f"{self.SYSTEM_PROMPT}\n\n{user_msg}"
        
        try:
            response = self.model.generate_content(prompt_completo)
            raw = response.text
            
            cleaned = raw.replace("```json", "").replace("```", "").strip()
            cleaned = "".join(c for c in cleaned if ord(c) >= 32 or c in "\n\r\t")
            
            parsed = json.loads(cleaned)
            results = parsed.get("results", [])
            
            return [r.replace("\\n", "\n") for r in results]
            
        except Exception as e:
            raise RuntimeError(f"❌ Erro ao gerar textos: {str(e)}")
