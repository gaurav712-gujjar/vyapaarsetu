"""
Parses an inbound WhatsApp/Instagram message into a structured intent using
Groq (fast Llama inference), so the conversation flow (conversation.py) can
decide what to do: show catalog, add an item, confirm the order, etc.

Requires GROQ_API_KEY in .env (get one free at https://console.groq.com/keys).
If it's missing or the call fails, falls back to a safe default (treated as
"show the catalog") so the bot never goes silent on a customer.
"""
import json
import logging
import requests

from .config import settings

logger = logging.getLogger("vyapaarsetu.llm")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama-3.3-70b-versatile"

FALLBACK = {
    "intent": "browse_catalog",
    "product_name": None,
    "quantity": 1,
    "reply_text": "Thanks for reaching out! Here's what we have — just reply with the item name to order.",
}


def parse_customer_message(catalog_text: str, conv_state: str, cart_text: str, user_message: str) -> dict:
    if not settings.GROQ_API_KEY:
        return dict(FALLBACK)

    system_prompt = f"""You are a warm, concise WhatsApp/Instagram shopping assistant for an Indian \
small-business storefront (VyapaarSetu). Conversation state: {conv_state}. Current cart: {cart_text or 'empty'}.

Catalog (name, price, category):
{catalog_text}

Classify the customer's latest message and draft a reply. Output ONLY valid JSON \
(no markdown fences, no extra text) matching exactly this shape:
{{"intent": "greeting|browse_catalog|select_item|confirm_order|cancel|other", "product_name": "<closest matching catalog product name, or null>", "quantity": <integer, default 1 if unspecified>, "reply_text": "<short warm reply to send the customer, under 300 characters, same language/script they used>"}}

Rules:
- If this is a greeting or the very first message, intent="greeting"; reply_text should welcome them and mention you'll show the menu/catalog.
- If they ask what's available / "menu" / "catalog", intent="browse_catalog".
- If they name a specific product (even partial/misspelled), intent="select_item" with the best-matching product_name from the catalog, and extract quantity if mentioned.
- If they say "confirm"/"haan"/"order karo"/"pay karo" while a cart item is pending, intent="confirm_order".
- If they want to cancel/stop, intent="cancel".
- Never invent a product_name that isn't in the catalog above."""

    try:
        resp = requests.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": 400,
                "temperature": 0.3,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
            },
            timeout=15,
        )
        resp.raise_for_status()
        raw_text = resp.json()["choices"][0]["message"]["content"].strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.strip("`")
            if raw_text.startswith("json"):
                raw_text = raw_text[4:].strip()
        parsed = json.loads(raw_text)
        parsed.setdefault("quantity", 1)
        parsed.setdefault("product_name", None)
        parsed.setdefault("reply_text", FALLBACK["reply_text"])
        parsed.setdefault("intent", "other")
        return parsed
    except Exception:
        logger.exception("LLM intent parse failed, using fallback")
        return dict(FALLBACK)