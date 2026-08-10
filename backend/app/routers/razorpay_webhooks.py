"""
Handles Razorpay's server-to-server webhook events for the WhatsApp/Instagram
payment-link flow (conversation.py creates the link; this is where we find
out what happened to it).

Configure in Razorpay Dashboard -> Settings -> Webhooks:
  URL:    https://<your-ngrok-or-domain>/api/webhooks/razorpay
  Secret: any string you choose, also put it in .env as RAZORPAY_WEBHOOK_SECRET
  Events: payment_link.paid, payment_link.expired, payment_link.cancelled

Note on the "reassure the customer" requirement: we only ever tell a customer
their payment succeeded when Razorpay has actually confirmed it (payment_link.paid).
If a link expires/is cancelled before payment, we tell them honestly that it
didn't go through and invite them to try again -- never claim a payment happened
when it didn't. The "payment's already gone through, refund is on its way" message
is reserved for the case where payment genuinely succeeded but something *after*
that (e.g. an inventory hiccup) failed on our side -- that's handled separately
in queue_worker.py via conversation.issue_refund_and_reassure().
"""
import hashlib
import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy.orm import Session
from fastapi import Depends

from ..config import settings
from ..database import get_db
from ..models import Order, PaymentStatusEnum, ConversationState
from ..queue_utils import enqueue_order_pipeline
from ..messaging import send_text

router = APIRouter(prefix="/api/webhooks/razorpay", tags=["razorpay-webhooks"])
logger = logging.getLogger("vyapaarsetu.razorpay_webhook")


def _verify_signature(raw_body: bytes, signature_header: str | None) -> bool:
    if not settings.RAZORPAY_WEBHOOK_SECRET:
        return True  # dev-only fallback, same pattern as meta_webhooks.py
    if not signature_header:
        return False
    expected = hmac.new(
        settings.RAZORPAY_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


@router.post("")
async def razorpay_events(
    request: Request,
    db: Session = Depends(get_db),
    x_razorpay_signature: str | None = Header(default=None),
):
    raw = await request.body()
    if not _verify_signature(raw, x_razorpay_signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    body = await request.json()
    event = body.get("event")
    logger.info("Razorpay webhook event: %s", event)

    if event == "payment_link.paid":
        link_entity = body["payload"]["payment_link"]["entity"]
        link_id = link_entity["id"]
        payment_entity = body["payload"].get("payment", {}).get("entity", {})
        payment_id = payment_entity.get("id")

        # conversation.py stored the payment LINK id in razorpay_order_id.
        order = db.query(Order).filter(Order.razorpay_order_id == link_id).first()
        if not order:
            logger.warning("payment_link.paid for unknown link_id %s", link_id)
            return {"status": "ignored"}

        if order.payment_status == PaymentStatusEnum.paid:
            return {"status": "already processed"}  # idempotent on Razorpay retries

        order.payment_status = PaymentStatusEnum.paid
        order.razorpay_payment_id = payment_id
        db.commit()
        enqueue_order_pipeline(db, order)  # verify_payment/update_inventory/send_confirmation
        return {"status": "ok"}

    if event in ("payment_link.expired", "payment_link.cancelled"):
        link_entity = body["payload"]["payment_link"]["entity"]
        link_id = link_entity["id"]
        order = db.query(Order).filter(Order.razorpay_order_id == link_id).first()
        if not order or order.payment_status == PaymentStatusEnum.paid:
            return {"status": "ignored"}

        order.payment_status = PaymentStatusEnum.failed
        db.commit()

        # Honest message -- payment did NOT happen, so we say so and invite a retry.
        conv = (
            db.query(ConversationState)
            .filter(ConversationState.pending_order_id == order.id)
            .first()
        )
        if conv:
            channel_val = conv.channel.value if hasattr(conv.channel, "value") else conv.channel
            send_text(
                channel_val, conv.external_id,
                "That payment link expired before completing. No charge was made -- "
                "just reply with the item name again whenever you're ready to order.",
            )
        return {"status": "ok"}

    return {"status": "ignored"}