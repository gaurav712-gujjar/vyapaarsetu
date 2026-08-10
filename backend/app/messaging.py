"""
Sends outbound text messages back to customers on WhatsApp / Instagram.

Requires (in .env):
  META_WHATSAPP_TOKEN, META_WHATSAPP_PHONE_NUMBER_ID  -- for WhatsApp
  META_PAGE_ACCESS_TOKEN                              -- for Instagram

If these aren't configured yet, sends are logged instead of actually sent
(useful for local testing without wiring up real Meta send permissions).
"""
import logging
import requests

from .config import settings

logger = logging.getLogger("vyapaarsetu.messaging")

GRAPH_API = "https://graph.facebook.com/v20.0"


def send_whatsapp_text(to: str, text: str) -> None:
    if not settings.META_WHATSAPP_TOKEN or not settings.META_WHATSAPP_PHONE_NUMBER_ID:
        logger.info("[whatsapp send SKIPPED, no token configured] -> %s: %s", to, text)
        return
    url = f"{GRAPH_API}/{settings.META_WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {settings.META_WHATSAPP_TOKEN}"}
    payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text}}
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
    except Exception:
        logger.exception("Failed to send WhatsApp message to %s", to)


def send_instagram_text(recipient_id: str, text: str) -> None:
    if not settings.META_PAGE_ACCESS_TOKEN:
        logger.info("[instagram send SKIPPED, no token configured] -> %s: %s", recipient_id, text)
        return
    url = f"{GRAPH_API}/me/messages"
    params = {"access_token": settings.META_PAGE_ACCESS_TOKEN}
    payload = {"recipient": {"id": recipient_id}, "message": {"text": text}}
    try:
        resp = requests.post(url, params=params, json=payload, timeout=10)
        resp.raise_for_status()
    except Exception:
        logger.exception("Failed to send Instagram message to %s", recipient_id)


def send_text(channel: str, external_id: str, text: str) -> None:
    """channel is a plain string here ('whatsapp' / 'instagram' / anything
    else), since callers may pass either the raw string or a ChannelEnum's
    .value -- keep this dumb and dispatch on string match."""
    if channel == "whatsapp":
        send_whatsapp_text(external_id, text)
    elif channel == "instagram":
        send_instagram_text(external_id, text)
    else:
        logger.info("[%s -> %s] %s", channel, external_id, text)