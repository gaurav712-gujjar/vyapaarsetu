"""
Parses an inbound WhatsApp/Instagram message into a structured intent using
Groq (fast Llama inference), so the conversation flow (conversation.py) can
decide what to do: show categories, show items in a category, add to cart,
confirm the order, check order status, etc.

Requires GROQ_API_KEY in .env (get one free at https://console.groq.com/keys).
If it's missing or the call fails, falls back to a safe default (treated as
"show categories") so the bot never goes silent on a customer.
"""
import json
import logging
import requests

from .config import settings

logger = logging.getLogger("vyapaarsetu.llm")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama-3.3-70b-versatile"

FALLBACK = {
    "intent": "browse_categories",
    "category_name": None,
    "product_name": None,
    "quantity": 1,
    "reply_text": "Thanks for reaching out! Here are our categories — just reply with one to see what's inside.",
}


def parse_customer_message(categories_text: str, catalog_text: str, conv_state: str, cart_text: str, user_message: str) -> dict:
    if not settings.GROQ_API_KEY:
        return dict(FALLBACK)

    system_prompt = f"""You are a warm, concise WhatsApp/Instagram shopping assistant for an Indian \
small-business storefront (VyapaarSetu). Conversation state: {conv_state}. Current cart: {cart_text or 'empty'}.

Categories available: {categories_text}

Catalog (name, price, category) -- for matching an already-shown item, not for listing in full:
{catalog_text}

Classify the customer's latest message and draft a reply. Output ONLY valid JSON \
(no markdown fences, no extra text) matching exactly this shape:
{{"intent": "greeting|browse_categories|select_category|show_more|select_item|confirm_order|order_status|cancel|restricted_info|other", "category_name": "<closest matching category name, or null>", "product_name": "<closest matching catalog product name, or null>", "quantity": <integer, default 1 if unspecified>, "reply_text": "<short warm reply to send the customer, under 300 characters, same language/script they used>"}}

Rules:
- If this is a greeting or the very first message, intent="greeting"; reply_text should welcome them briefly -- the categories list is sent separately, don't restate it.
- If they ask what's available / "menu" / "categories", intent="browse_categories".
- If they name a category (even partial/misspelled), intent="select_category" with the best-matching category_name.
- If they ask to see more / "next" / "aur dikhao", intent="show_more".
- If they name a specific product (even partial/misspelled) that was already shown to them, intent="select_item" with the best-matching product_name, and extract quantity if mentioned.
- If they say "confirm"/"haan"/"order karo"/"pay karo" while a cart item is pending AND conversation state is NOT "awaiting_payment", intent="confirm_order".
- If conversation state is "awaiting_payment", they already have a payment link. Any message about payment status/confirmation -- "I paid", "maine paisa bhej diya", "payment done", "no confirmation yet", "kab confirm hoga", "already paid" -- is intent="order_status". NEVER intent="confirm_order" in this state; do not send another payment link for a payment that's already in progress.
- If they ask about an existing order -- status, confirmation, invoice, "where is my order", "order number X" -- intent="order_status".
- If they want to cancel/stop, intent="cancel".
- If they ask about stock levels, how many units are left, warehouse inventory, sales figures, revenue, or any internal business numbers, intent="restricted_info"; reply_text should politely say that information isn't something you can share, without guessing or making up a number.
- Never invent a product_name or category_name that isn't in the lists above.
- For general questions not covered above (delivery time, returns, payment methods, greetings, thanks, small talk), intent="other" and write a direct, helpful reply_text yourself instead of a generic "could you rephrase" filler -- only use a rephrase-style reply if the message is genuinely unclear."""

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
        parsed.setdefault("category_name", None)
        parsed.setdefault("reply_text", FALLBACK["reply_text"])
        parsed.setdefault("intent", "other")
        return parsed
    except Exception:
        logger.exception("LLM intent parse failed, using fallback")
        return dict(FALLBACK)