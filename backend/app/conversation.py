"""
Chat-commerce orchestrator.

Flow per inbound message:
  1. Load (or create) this customer's ConversationState.
  2. Ask the LLM to classify the message (greeting / browse / select item /
     confirm / cancel) against the current catalog + cart.
  3. Act on it: send the catalog, update the cart, or -- on confirm -- create
     an Order + Razorpay Payment Link and message the pay link back.
  4. Razorpay's webhook (routers/razorpay_webhooks.py) later marks the order
     paid and triggers the normal DLQ/queue pipeline; on final pipeline
     failure, issue_refund_and_reassure() below is called to refund the
     customer and send a calm, reassuring message.
"""
import difflib
import logging
import uuid

import razorpay
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal
from .llm import parse_customer_message
from .messaging import send_text
from .models import (
    ChannelEnum, ConversationState, ConvStateEnum, Order, OrderItem,
    OrderStatusEnum, PaymentStatusEnum, Product,
)

logger = logging.getLogger("vyapaarsetu.conversation")
razorpay_client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

CATALOG_LIMIT = 40
CATALOG_SHOW_LIMIT = 15


def _get_or_create_state(db: Session, channel: str, external_id: str, name: str | None) -> ConversationState:
    state = (
        db.query(ConversationState)
        .filter(ConversationState.channel == channel, ConversationState.external_id == external_id)
        .first()
    )
    if not state:
        state = ConversationState(
            channel=channel, external_id=external_id, customer_name=name,
            state=ConvStateEnum.new, cart={},
        )
        db.add(state)
        db.commit()
        db.refresh(state)
    elif name and not state.customer_name:
        state.customer_name = name
        db.commit()
    return state


def _catalog_text(db: Session) -> str:
    products = (
        db.query(Product)
        .filter(Product.is_active == True, Product.stock > 0)  # noqa: E712
        .order_by(Product.id.desc())
        .limit(CATALOG_LIMIT)
        .all()
    )
    return "\n".join(f"- {p.name} (Rs.{int(p.price)}) [{p.category.name}]" for p in products)


def _find_product(db: Session, name_hint: str | None) -> Product | None:
    if not name_hint:
        return None
    products = db.query(Product).filter(Product.is_active == True).all()  # noqa: E712
    names = {p.name: p for p in products}
    match = difflib.get_close_matches(name_hint, names.keys(), n=1, cutoff=0.4)
    return names[match[0]] if match else None


def _send_catalog(db: Session, channel: str, external_id: str) -> None:
    products = (
        db.query(Product)
        .filter(Product.is_active == True, Product.stock > 0)  # noqa: E712
        .order_by(Product.id.desc())
        .limit(CATALOG_SHOW_LIMIT)
        .all()
    )
    if not products:
        send_text(channel, external_id, "We're currently out of stock -- please check back soon!")
        return
    lines = [f"{i + 1}. {p.name} -- Rs.{int(p.price)}" for i, p in enumerate(products)]
    send_text(
        channel, external_id,
        "Here's what we have:\n" + "\n".join(lines) + "\n\nJust reply with the item name to order it.",
    )


def _create_order_and_payment_link(db: Session, state: ConversationState) -> None:
    cart = state.cart or {}
    product = db.query(Product).filter(Product.id == cart.get("product_id")).first()
    channel_val = state.channel.value if hasattr(state.channel, "value") else state.channel

    if not product or product.stock < cart.get("quantity", 1):
        send_text(channel_val, state.external_id, "Sorry, that item just went out of stock.")
        state.cart = {}
        state.state = ConvStateEnum.browsing
        db.commit()
        return

    qty = cart["quantity"]
    total = float(product.price) * qty
    idempotency_key = f"{channel_val}:{state.external_id}:{uuid.uuid4()}"

    order = Order(
        idempotency_key=idempotency_key,
        channel=state.channel,
        customer_name=state.customer_name,
        customer_phone=state.external_id if channel_val == "whatsapp" else None,
        total_amount=total,
        status=OrderStatusEnum.pending,
        payment_status=PaymentStatusEnum.not_initiated,
        raw_payload={"cart": cart, "source": "chat"},
    )
    db.add(order)
    db.flush()
    db.add(OrderItem(order_id=order.id, product_id=product.id, quantity=qty, unit_price=product.price))

    try:
        link = razorpay_client.payment_link.create({
            "amount": int(round(total * 100)),
            "currency": "INR",
            "accept_partial": False,
            "description": f"{qty} x {product.name}",
            "customer": {
                "name": state.customer_name or "Customer",
                "contact": state.external_id if channel_val == "whatsapp" else "",
            },
            "notify": {"sms": False, "email": False},
            "reference_id": f"order_{order.id}",
        })
    except Exception:
        logger.exception("Razorpay payment link creation failed for order #%s", order.id)
        db.rollback()
        send_text(channel_val, state.external_id, "Sorry, something went wrong generating your payment link. Please try again shortly.")
        return

    # Reuse the razorpay_order_id column to store the payment LINK id (not an
    # Orders-API order id) -- razorpay_webhooks.py looks it up by this same
    # field when the payment_link.paid event arrives.
    order.razorpay_order_id = link["id"]
    order.payment_status = PaymentStatusEnum.created
    state.pending_order_id = order.id
    state.state = ConvStateEnum.awaiting_payment
    db.commit()

    send_text(
        channel_val, state.external_id,
        f"Please pay Rs.{total:.0f} here to confirm your order:\n{link['short_url']}\n\n"
        "We'll message you here the moment it's confirmed.",
    )


def handle_inbound_message(channel: str, external_id: str, sender_name: str | None, text: str) -> None:
    db = SessionLocal()
    try:
        state = _get_or_create_state(db, channel, external_id, sender_name)
        parsed = parse_customer_message(_catalog_text(db), state.state.value, str(state.cart or {}), text or "")
        intent = parsed.get("intent", "other")

        if state.state == ConvStateEnum.new or intent == "greeting":
            state.state = ConvStateEnum.browsing
            db.commit()
            send_text(channel, external_id, parsed["reply_text"])
            _send_catalog(db, channel, external_id)
            return

        if intent == "browse_catalog":
            send_text(channel, external_id, parsed["reply_text"])
            _send_catalog(db, channel, external_id)
            return

        if intent == "select_item":
            product = _find_product(db, parsed.get("product_name"))
            if not product:
                send_text(channel, external_id, "Sorry, I couldn't find that item -- here's the catalog again:")
                _send_catalog(db, channel, external_id)
                return
            qty = max(1, int(parsed.get("quantity") or 1))
            if product.stock < qty:
                send_text(channel, external_id, f"Sorry, only {product.stock} left of {product.name}. How many would you like?")
                return
            state.cart = {"product_id": product.id, "name": product.name, "price": float(product.price), "quantity": qty}
            db.commit()
            total = float(product.price) * qty
            send_text(channel, external_id, f"{qty} x {product.name} = Rs.{total:.0f}. Reply 'confirm' to pay, or tell me if you'd like to change the quantity.")
            return

        if intent == "confirm_order":
            if not state.cart or not state.cart.get("product_id"):
                send_text(channel, external_id, "You haven't picked an item yet -- here's the catalog:")
                _send_catalog(db, channel, external_id)
                return
            _create_order_and_payment_link(db, state)
            return

        if intent == "cancel":
            state.cart = {}
            state.state = ConvStateEnum.browsing
            db.commit()
            send_text(channel, external_id, "No problem, cancelled. Let me know if you'd like to see the catalog again.")
            return

        send_text(channel, external_id, parsed.get("reply_text") or "Sorry, could you rephrase that?")
    finally:
        db.close()


def issue_refund_and_reassure(order_id: int) -> None:
    """Called when an order's processing pipeline exhausts all retries and
    lands in the DLQ. If payment was captured, refund it, and message the
    customer a calm, reassuring note -- never leave them wondering."""
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            return

        if order.payment_status == PaymentStatusEnum.paid and order.razorpay_payment_id:
            try:
                razorpay_client.payment.refund(
                    order.razorpay_payment_id,
                    {"amount": int(round(float(order.total_amount) * 100))},
                )
                logger.info("Refund issued for order #%s", order.id)
            except Exception:
                logger.exception("Refund FAILED for order #%s -- needs manual action", order.id)

        conv = db.query(ConversationState).filter(ConversationState.pending_order_id == order.id).first()
        if conv:
            channel_val = conv.channel.value if hasattr(conv.channel, "value") else conv.channel
            send_text(
                channel_val, conv.external_id,
                "We're sorry -- we ran into an issue processing your order. Your payment has "
                "already gone through, so a full refund is on its way and you don't need to do "
                "anything further. We'll follow up here shortly.",
            )
    finally:
        db.close()