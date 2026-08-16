"""
Chat-commerce orchestrator.

Flow per inbound message:
  1. Load (or create) this customer's ConversationState.
  2. Ask the LLM to classify the message against categories/catalog/cart/state.
  3. Act on it:
     - greeting/browse_categories -> list categories
     - select_category -> show first page of items in that category, WITH IMAGES
     - show_more -> next page of the same category
     - select_item -> add to cart
     - confirm_order -> create an Order + Razorpay Payment Link, message it back
     - order_status -> look up and describe the customer's most recent order
     - restricted_info -> politely decline (stock counts / revenue are never
       exposed here -- that data only exists behind the admin-only,
       require_admin-gated dashboard endpoints; the chat layer never queries
       it in the first place)
  4. Razorpay's webhook (routers/razorpay_webhooks.py) later marks the order
     paid and triggers the normal DLQ/queue pipeline. If payment itself fails
     to confirm, or a later pipeline step fails permanently, the customer is
     messaged honestly -- see queue_worker.py's DLQ handling for the exact
     wording logic (never claims a payment succeeded when it didn't).
"""
import difflib
import logging
import uuid

import razorpay
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal
from .llm import parse_customer_message
from .messaging import send_text, send_image
from .queue_utils import enqueue_order_pipeline

from .models import (
    Category, ChannelEnum, ConversationState, ConvStateEnum, Order, OrderItem,
    OrderStatusEnum, PaymentStatusEnum, Product,
)

logger = logging.getLogger("vyapaarsetu.conversation")
razorpay_client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

CATALOG_LIMIT = 60          # products considered when the LLM matches a name
CATEGORY_PAGE_SIZE = 5      # items shown per page within a category (each is its own image message)


def _get_or_create_state(db: Session, channel: str, external_id: str, name: str | None) -> ConversationState:
    state = (
        db.query(ConversationState)
        .filter(ConversationState.channel == channel, ConversationState.external_id == external_id)
        .first()
    )
    if not state:
        state = ConversationState(
            channel=channel, external_id=external_id, customer_name=name,
            state=ConvStateEnum.new, cart={}, context={},
        )
        db.add(state)
        db.commit()
        db.refresh(state)
    elif name and not state.customer_name:
        state.customer_name = name
        db.commit()
    return state


def _categories_text(db: Session) -> str:
    cats = db.query(Category).order_by(Category.name).all()
    return ", ".join(c.name for c in cats)


def _catalog_text(db: Session) -> str:
    products = (
        db.query(Product)
        .filter(Product.is_active == True, Product.stock > 0)  # noqa: E712
        .order_by(Product.id.desc())
        .limit(CATALOG_LIMIT)
        .all()
    )
    # Deliberately: name, price, category only -- never stock count or cost/revenue data.
    return "\n".join(f"- {p.name} (Rs.{int(p.price)}) [{p.category.name}]" for p in products)

def _category_catalog_text(db: Session, category_id: int) -> str:
    products = (
        db.query(Product)
        .filter(Product.category_id == category_id, Product.is_active == True, Product.stock > 0)  # noqa: E712
        .order_by(Product.id.desc())
        .all()
    )
    return "\n".join(f"- {p.name} (Rs.{int(p.price)}) [{p.category.name}]" for p in products)


def _find_product(db: Session, name_hint: str | None) -> Product | None:
    if not name_hint:
        return None
    # Only match against in-stock products -- same filter used everywhere else
    # a customer-facing product list is built (_catalog_text, _send_category_page).
    # Otherwise a similarly-named but out-of-stock product can win the fuzzy
    # match (cutoff=0.4 is loose) and the customer wrongly gets an "out of
    # stock" reply for an item that's actually available.
    products = db.query(Product).filter(Product.is_active == True, Product.stock > 0).all()  # noqa: E712
    names = {p.name: p for p in products}
    match = difflib.get_close_matches(name_hint, names.keys(), n=1, cutoff=0.4)
    return names[match[0]] if match else None


def _find_category(db: Session, name_hint: str | None) -> Category | None:
    if not name_hint:
        return None
    cats = db.query(Category).all()
    names = {c.name: c for c in cats}
    match = difflib.get_close_matches(name_hint, names.keys(), n=1, cutoff=0.4)
    return names[match[0]] if match else None


def _send_categories(db: Session, channel: str, external_id: str) -> None:
    cats = db.query(Category).order_by(Category.name).all()
    if not cats:
        send_text(channel, external_id, "We don't have any categories set up yet -- please check back soon!")
        return
    lines = [f"{i + 1}. {c.name}" for i, c in enumerate(cats)]
    send_text(
        channel, external_id,
        "Here's what we sell:\n" + "\n".join(lines) + "\n\nReply with a category name to see what's inside.",
    )


def _send_category_page(db: Session, state: ConversationState, category: Category, offset: int) -> None:
    channel_val = state.channel.value if hasattr(state.channel, "value") else state.channel
    products = (
        db.query(Product)
        .filter(Product.category_id == category.id, Product.is_active == True, Product.stock > 0)  # noqa: E712
        .order_by(Product.id.desc())
        .offset(offset)
        .limit(CATEGORY_PAGE_SIZE)
        .all()
    )
    if not products:
        if offset == 0:
            send_text(channel_val, state.external_id, f"Nothing available in {category.name} right now -- check back soon!")
        else:
            send_text(channel_val, state.external_id, "That's everything in this category.")
        return

    for p in products:
        caption = f"{p.name} -- Rs.{int(p.price)}"
        if p.image_url:
            send_image(channel_val, state.external_id, p.image_url, caption)
        else:
            send_text(channel_val, state.external_id, caption)

    # Peek one past the page to know whether to offer "show more".
    has_more = (
        db.query(Product)
        .filter(Product.category_id == category.id, Product.is_active == True, Product.stock > 0)  # noqa: E712
        .order_by(Product.id.desc())
        .offset(offset + CATEGORY_PAGE_SIZE)
        .limit(1)
        .first()
        is not None
    )
    footer = "Reply with an item name to order it."
    if has_more:
        footer += " Or reply 'more' to see more items in this category."
    send_text(channel_val, state.external_id, footer)

    state.context = {**(state.context or {}), "category_id": category.id, "offset": offset}


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

    payment_link_payload = {
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
    }
    if channel_val == "whatsapp" and settings.WHATSAPP_BUSINESS_NUMBER:
        # Send the customer straight back into this WhatsApp chat once they're
        # done on Razorpay's page, instead of leaving them stranded there.
        # This redirect is UX only -- actual confirmation still comes from
        # the payment_link.paid webhook, never from this callback alone.
        payment_link_payload["callback_url"] = f"https://wa.me/{settings.WHATSAPP_BUSINESS_NUMBER}"
        payment_link_payload["callback_method"] = "get"

    try:
        link = razorpay_client.payment_link.create(payment_link_payload)
    except Exception:
        logger.exception("Razorpay payment link creation failed for order #%s", order.id)
        db.rollback()
        send_text(channel_val, state.external_id, "Sorry, something went wrong generating your payment link. Please try again shortly.")
        return

    # Reuse the razorpay_order_id column to store the payment LINK id (not an
    # Orders-API order id) -- razorpay_webhooks.py and queue_worker.py's
    # retry_payment_check handler both look this up the same way.
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


def _describe_order(db: Session, state: ConversationState) -> str:
    """Builds a customer-facing order status/confirmation summary. Only ever
    pulls order-level fields (status, items, total, payment) -- never touches
    stock or revenue data, which live behind separate admin-only endpoints."""
    order = None
    if state.pending_order_id:
        order = db.query(Order).filter(Order.id == state.pending_order_id).first()
    if not order:
        return "I don't see any orders on your account yet -- reply with a category name to start one!"

    # Self-heal a stale "created" status: if the payment_link.paid webhook
    # is delayed or was missed, check directly with Razorpay before telling
    # the customer nothing has happened -- this is exactly what "I paid but
    # got no confirmation" messages need.
    if order.payment_status == PaymentStatusEnum.created and order.razorpay_order_id:
        try:
            link = razorpay_client.payment_link.fetch(order.razorpay_order_id)
            if link.get("status") == "paid":
                order.payment_status = PaymentStatusEnum.paid
                payments = link.get("payments") or []
                if payments:
                    order.razorpay_payment_id = payments[-1].get("payment_id")
                db.commit()
                enqueue_order_pipeline(db, order)
        except Exception:
            logger.exception("Live Razorpay status check failed for order #%s", order.id)

    items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
    item_lines = []
    for it in items:
        product = db.query(Product).filter(Product.id == it.product_id).first()
        name = product.name if product else "item"
        item_lines.append(f"{it.quantity} x {name}")

    status_word = {
        OrderStatusEnum.confirmed: "Confirmed",
        OrderStatusEnum.flagged: "Being reviewed by our team",
        OrderStatusEnum.failed: "Payment not completed",
    }.get(order.status, "In progress")

    payment_word = {
        PaymentStatusEnum.not_initiated: "Not started",
        PaymentStatusEnum.created: "Link sent -- waiting for you to complete payment",
        PaymentStatusEnum.paid: "Paid",
        PaymentStatusEnum.failed: "Failed",
    }.get(order.payment_status, order.payment_status.value)

    return (
        f"Order #{order.id}\n"
        f"Items: {', '.join(item_lines) if item_lines else '—'}\n"
        f"Total: Rs.{float(order.total_amount):.0f}\n"
        f"Payment: {payment_word}\n"
        f"Status: {status_word}"
    )

    return (
        f"Order #{order.id}\n"
        f"Items: {', '.join(item_lines) if item_lines else '—'}\n"
        f"Total: Rs.{float(order.total_amount):.0f}\n"
        f"Payment: {order.payment_status.value}\n"
        f"Status: {status_word}"
    )


def handle_inbound_message(channel: str, external_id: str, sender_name: str | None, text: str) -> None:
    db = SessionLocal()
    try:
        state = _get_or_create_state(db, channel, external_id, sender_name)
        current_category_id = (state.context or {}).get("category_id")
        catalog_for_llm = (
            _category_catalog_text(db, current_category_id) if current_category_id else _catalog_text(db)
        )
        parsed = parse_customer_message(
            _categories_text(db), catalog_for_llm, state.state.value, str(state.cart or {}), text or "",
        )
        intent = parsed.get("intent", "other")

        if state.state == ConvStateEnum.new or intent == "greeting":
            state.state = ConvStateEnum.browsing
            db.commit()
            send_text(channel, external_id, parsed["reply_text"])
            _send_categories(db, channel, external_id)
            return

        if intent == "browse_categories":
            send_text(channel, external_id, parsed["reply_text"])
            _send_categories(db, channel, external_id)
            return

        if intent == "select_category":
            category = _find_category(db, parsed.get("category_name"))
            if not category:
                send_text(channel, external_id, "Sorry, I couldn't find that category -- here they are again:")
                _send_categories(db, channel, external_id)
                return
            _send_category_page(db, state, category, offset=0)
            db.commit()
            return

        if intent == "show_more":
            ctx = state.context or {}
            category = db.query(Category).filter(Category.id == ctx.get("category_id")).first()
            if not category:
                send_text(channel, external_id, "Not sure which category you meant -- here they are:")
                _send_categories(db, channel, external_id)
                return
            next_offset = int(ctx.get("offset", 0)) + CATEGORY_PAGE_SIZE
            _send_category_page(db, state, category, offset=next_offset)
            db.commit()
            return

        if intent == "select_item":
            product = _find_product(db, parsed.get("product_name"))
            if not product:
                send_text(channel, external_id, "Sorry, I couldn't find that item -- here are our categories again:")
                _send_categories(db, channel, external_id)
                return
            qty = max(1, int(parsed.get("quantity") or 1))
            if product.stock < qty:
                send_text(channel, external_id, f"Sorry, we don't have that many available. How many would you like instead?")
                return
            state.cart = {"product_id": product.id, "name": product.name, "price": float(product.price), "quantity": qty}
            db.commit()
            total = float(product.price) * qty
            send_text(channel, external_id, f"{qty} x {product.name} = Rs.{total:.0f}. Reply 'confirm' to pay, or tell me if you'd like to change the quantity.")
            return

        if intent == "confirm_order":
            if state.state == ConvStateEnum.awaiting_payment and state.pending_order_id:
                # An order is already awaiting payment for this customer --
                # never spin up a second Order/payment link for the same
                # cart. Show the real, live-checked status instead.
                send_text(channel, external_id, _describe_order(db, state))
                return
            if not state.cart or not state.cart.get("product_id"):
                send_text(channel, external_id, "You haven't picked an item yet -- here are our categories:")
                _send_categories(db, channel, external_id)
                return
            _create_order_and_payment_link(db, state)
            return

        if intent == "order_status":
            send_text(channel, external_id, _describe_order(db, state))
            return

        if intent == "restricted_info":
            send_text(
                channel, external_id,
                parsed.get("reply_text") or "Sorry, that's not something I'm able to share here. "
                "Happy to help you browse or check an order instead!",
            )
            return

        if intent == "cancel":
            state.cart = {}
            state.state = ConvStateEnum.browsing
            db.commit()
            send_text(channel, external_id, "No problem, cancelled. Let me know if you'd like to see our categories again.")
            return

        send_text(channel, external_id, parsed.get("reply_text") or "Sorry, could you rephrase that?")
    finally:
        db.close()


def issue_refund_and_reassure(order_id: int) -> None:
    """Called when an order's processing pipeline exhausts all retries AFTER
    payment already succeeded (e.g. an inventory-step failure) and lands in
    the DLQ. Refunds the payment and sends a calm, honest, reassuring note.
    NOT used for payments that never went through in the first place -- see
    queue_worker.py's DLQ branch, which routes those to an honest "that
    didn't go through" message instead (send_payment_failed_message below)."""
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
                "already gone through, so please don't worry: a full refund is being processed "
                "and will reach you shortly, and our team will personally reach out to you here "
                "soon. You don't need to do anything further.",
            )
    finally:
        db.close()


def send_payment_failed_message(order_id: int) -> None:
    """Honest counterpart to issue_refund_and_reassure(): used when a payment
    genuinely never completed (no charge occurred), after backend auto-retry
    confirmed it via Razorpay. Never claims money was taken."""
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            return
        conv = db.query(ConversationState).filter(ConversationState.pending_order_id == order.id).first()
        if conv:
            channel_val = conv.channel.value if hasattr(conv.channel, "value") else conv.channel
            send_text(
                channel_val, conv.external_id,
                "That payment didn't go through and no charge was made. Whenever you're ready, "
                "just reply with the item name again and I'll send a fresh payment link.",
            )
    finally:
        db.close()