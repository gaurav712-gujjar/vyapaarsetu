"""
Adapter for Meta's real WhatsApp Cloud API / Instagram Messaging webhooks.

Meta's webhook flow has two parts:
1. VERIFICATION (GET): when you save the webhook URL in the Meta App Dashboard,
   Meta sends a GET request with hub.mode/hub.verify_token/hub.challenge. You
   must echo back hub.challenge if the token matches, or Meta refuses to save
   the webhook.
2. EVENTS (POST): every incoming message/order event is POSTed here in Meta's
   own nested JSON shape (very different from our normalized WebhookOrderPayload).
   This file extracts the useful fields and calls the same
   create_order_from_channel() used by the generic /api/webhooks/{channel} route,
   so idempotency, item resolution, and the processing pipeline all stay shared.

Set META_VERIFY_TOKEN and META_APP_SECRET in your .env (see .env.example).
"""
import hashlib
import hmac
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..conversation import handle_inbound_message

router = APIRouter(prefix="/api/webhooks/meta", tags=["meta-webhooks"])
logger = logging.getLogger("vyapaarsetu.meta")


# ---------------------------------------------------------------------------
# Step 1: Verification handshake (Meta calls this once, when you click "Verify
# and Save" in the App Dashboard webhook config screen).
# ---------------------------------------------------------------------------
@router.get("/whatsapp")
@router.get("/instagram")
async def verify_webhook(request: Request):
    # Meta sends hub.mode / hub.verify_token / hub.challenge as query params.
    # FastAPI can't bind dotted names as function args, so read them from
    # request.query_params directly.
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == settings.META_VERIFY_TOKEN:
        logger.info("Meta webhook verified successfully")
        return PlainTextResponse(content=challenge or "", status_code=200)

    raise HTTPException(status_code=403, detail="Verification token mismatch")


# ---------------------------------------------------------------------------
# Step 2: helper to verify Meta's request signature (recommended for production
# so random requests can't forge orders into your system).
# ---------------------------------------------------------------------------
def _verify_signature(raw_body: bytes, signature_header: str | None) -> bool:
    if not settings.META_APP_SECRET:
        return True  # signature check skipped if no app secret configured (dev only)
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(
        settings.META_APP_SECRET.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header.split("sha256=", 1)[1])


# ---------------------------------------------------------------------------
# Step 3: real event ingestion for WhatsApp
# ---------------------------------------------------------------------------
@router.post("/whatsapp")
async def whatsapp_events(
    request: Request,
    db: Session = Depends(get_db),
    x_hub_signature_256: str | None = Header(default=None),
):
    raw = await request.body()
    if not _verify_signature(raw, x_hub_signature_256):
        raise HTTPException(status_code=403, detail="Invalid signature")

    body = await request.json()
    handled = []

    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for msg in value.get("messages", []):
                if msg.get("type") != "text":
                    continue
                wa_id = msg.get("from")
                text = msg.get("text", {}).get("body", "")
                contacts = value.get("contacts", [])
                name = contacts[0]["profile"]["name"] if contacts else None

                # This talks to Claude (intent parsing) and sends WhatsApp
                # replies itself -- greeting, catalog, cart, payment link, etc.
                # See conversation.py for the full state machine.
                handle_inbound_message("whatsapp", wa_id, name, text)
                handled.append(wa_id)

    return {"status": "ok", "handled": handled}


# ---------------------------------------------------------------------------
# Step 4: real event ingestion for Instagram DMs
# ---------------------------------------------------------------------------
@router.post("/instagram")
async def instagram_events(
    request: Request,
    db: Session = Depends(get_db),
    x_hub_signature_256: str | None = Header(default=None),
):
    raw = await request.body()
    if not _verify_signature(raw, x_hub_signature_256):
        raise HTTPException(status_code=403, detail="Invalid signature")

    body = await request.json()
    handled = []

    for entry in body.get("entry", []):
        for messaging in entry.get("messaging", []):
            message = messaging.get("message", {})
            if message.get("is_echo"):
                continue  # skip messages the business itself sent
            sender_id = messaging.get("sender", {}).get("id")
            text = message.get("text", "")

            handle_inbound_message("instagram", sender_id, None, text)
            handled.append(sender_id)

    return {"status": "ok", "handled": handled}