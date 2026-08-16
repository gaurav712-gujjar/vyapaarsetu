"""
MySQL-backed queue worker.

Design notes (since MySQL is used as the queue instead of Redis/Kafka):
- `event_queue` rows are claimed with SELECT ... FOR UPDATE SKIP LOCKED so multiple
  worker processes can run without double-processing the same row.
- The three pipeline steps for a given order (verify_payment -> update_inventory ->
  send_confirmation) are inserted together with ascending ids, and this worker always
  polls in `ORDER BY id ASC`, so steps naturally execute in order for a single worker.
  If you scale to multiple worker processes, add an explicit "previous step done"
  check before claiming a row.
- Failures increment retry_count and set next_retry_at using exponential backoff.
  After MAX_RETRIES the row is moved to `dlq_items` and the order is flagged for
  manual review on the dashboard.
"""
import asyncio
import logging
import random
import uuid
import razorpay
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..config import settings
from ..messaging import send_text
from ..conversation import issue_refund_and_reassure, send_payment_failed_message
from ..queue_utils import enqueue_order_pipeline
from ..models import (
    EventQueue, QueueStatusEnum, EventTypeEnum,
    Order, OrderStatusEnum, PaymentStatusEnum,
    OrderItem, Product, DlqItem, ChannelEnum,
)

logger = logging.getLogger("vyapaarsetu.worker")
WORKER_ID = f"worker-{uuid.uuid4().hex[:8]}"


def _claim_next_event(db: Session) -> EventQueue | None:
    now = datetime.utcnow()
    candidates = (
        db.query(EventQueue)
        .filter(
            EventQueue.status == QueueStatusEnum.pending,
            (EventQueue.next_retry_at.is_(None)) | (EventQueue.next_retry_at <= now),
        )
        .order_by(EventQueue.id.asc())
        .with_for_update(skip_locked=True)
        .limit(50)
        .all()
    )
    for row in candidates:
        # Don't let a later pipeline step (e.g. send_confirmation) jump ahead of an
        # earlier one for the same order that hasn't finished yet -- this matters
        # specifically while an earlier step is sitting in retry backoff.
        blocked = (
            db.query(EventQueue)
            .filter(
                EventQueue.order_id == row.order_id,
                EventQueue.id < row.id,
                EventQueue.status != QueueStatusEnum.done,
            )
            .first()
        )
        if blocked:
            continue
        row.status = QueueStatusEnum.processing
        row.worker_id = WORKER_ID
        db.commit()
        return row
    return None


def _handle_verify_payment(db: Session, order: Order) -> None:
    if order.channel == ChannelEnum.website:
        if order.payment_status != PaymentStatusEnum.paid:
            raise RuntimeError("Website order reached queue without a verified payment")
    else:
        # Non-website channels (WhatsApp / Instagram / delivery partner) are typically
        # COD or pre-arranged. Simulate a verification/confirmation check here; swap
        # in a real COD-confirmation or partner-payment API call as needed.
        order.payment_status = PaymentStatusEnum.paid
    order.status = OrderStatusEnum.payment_verified
    db.commit()


def _handle_update_inventory(db: Session, order: Order) -> None:
    items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
    for item in items:
        product = db.query(Product).filter(Product.id == item.product_id).with_for_update().first()
        if not product:
            continue
        if product.stock < item.quantity:
            raise RuntimeError(f"Insufficient stock for product #{product.id} ({product.name})")
        product.stock -= item.quantity
    order.status = OrderStatusEnum.inventory_updated
    db.commit()


def _handle_send_confirmation(db: Session, order: Order) -> None:
    channel_val = order.channel.value if hasattr(order.channel, "value") else order.channel
    if channel_val in ("whatsapp", "instagram"):
        # order.customer_phone doubles as the WhatsApp wa_id for chat orders;
        # for Instagram the sender psid is looked up via ConversationState.
        target = order.customer_phone
        if channel_val == "instagram":
            from ..models import ConversationState
            conv = db.query(ConversationState).filter(ConversationState.pending_order_id == order.id).first()
            target = conv.external_id if conv else None
        if target:
            send_text(channel_val, target, f"Your order #{order.id} is confirmed! Thank you for shopping with us.")
    logger.info(
        "Order confirmation sent to %s (%s) for order #%s",
        order.customer_name, order.customer_phone, order.id,
    )
    order.status = OrderStatusEnum.confirmed
    db.commit()


def _handle_retry_payment_check(db: Session, order: Order) -> None:
    """
    Runs when a payment is reported failed/dismissed/expired -- from the
    website (POST /api/orders/{id}/payment-retry) or from a chat-commerce
    payment link (payment_link.expired/cancelled webhook). Rather than
    trusting that signal alone, we ask Razorpay directly whether money
    actually moved -- covers races like a bank confirming a split-second
    after the browser/webhook reported failure.

    If Razorpay confirms paid -> mark paid, hand off to the normal pipeline.
    If not paid yet -> raise, which triggers the SAME automatic exponential-
    backoff retry (_process_event below) as every other pipeline step, and
    after MAX_RETRIES the order lands in the DLQ exactly like any other
    permanently-failed step.
    """
    if order.payment_status == PaymentStatusEnum.paid:
        return  # already resolved by a concurrent verify/webhook call

    razorpay_client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    channel_val = order.channel.value if hasattr(order.channel, "value") else order.channel

    if channel_val in ("whatsapp", "instagram"):
        # order.razorpay_order_id holds a Payment LINK id for chat-commerce orders.
        link = razorpay_client.payment_link.fetch(order.razorpay_order_id)
        paid = link.get("status") == "paid"
        status_label = link.get("status")
    else:
        rp_order = razorpay_client.order.fetch(order.razorpay_order_id)
        paid = rp_order.get("status") == "paid"
        status_label = rp_order.get("status")

    if paid:
        order.payment_status = PaymentStatusEnum.paid
        db.commit()
        enqueue_order_pipeline(db, order)
        return

    raise RuntimeError(f"Razorpay payment for order #{order.id} not yet paid (status={status_label})")


HANDLERS = {
    EventTypeEnum.verify_payment: _handle_verify_payment,
    EventTypeEnum.update_inventory: _handle_update_inventory,
    EventTypeEnum.send_confirmation: _handle_send_confirmation,
    EventTypeEnum.retry_payment_check: _handle_retry_payment_check,
}


def _process_event(db: Session, event: EventQueue) -> None:
    order = db.query(Order).filter(Order.id == event.order_id).with_for_update().first()
    if not order:
        event.status = QueueStatusEnum.failed
        db.commit()
        return

    try:
        order.status = OrderStatusEnum.processing
        db.commit()

        handler = HANDLERS[event.event_type]
        handler(db, order)

        event.status = QueueStatusEnum.done
        db.commit()

    except Exception as exc:  # noqa: BLE001
        db.rollback()
        event.retry_count += 1
        event.error_message = str(exc)[:1000]

        if event.retry_count >= settings.MAX_RETRIES:
            event.status = QueueStatusEnum.failed
            order.status = OrderStatusEnum.flagged
            db.add(DlqItem(
                order_id=order.id,
                event_queue_id=event.id,
                failed_step=event.event_type.value,
                error_message=event.error_message,
                retry_count=event.retry_count,
            ))
            logger.warning("Order #%s step '%s' moved to DLQ after %s retries",
                            order.id, event.event_type.value, event.retry_count)

            channel_val = order.channel.value if hasattr(order.channel, "value") else order.channel
            if channel_val in ("whatsapp", "instagram"):
                if event.event_type == EventTypeEnum.retry_payment_check and order.payment_status != PaymentStatusEnum.paid:
                    # Payment genuinely never went through -- say so honestly,
                    # never claim money was taken.
                    send_payment_failed_message(order.id)
                else:
                    # Payment already succeeded (verify_payment step passed) but
                    # something downstream failed permanently -- refund it and
                    # tell the customer honestly, rather than leaving them guessing.
                    issue_refund_and_reassure(order.id)
        else:
            backoff_seconds = (2 ** event.retry_count) + random.uniform(0, 1)
            event.status = QueueStatusEnum.pending
            event.next_retry_at = datetime.utcnow() + timedelta(seconds=backoff_seconds)
            logger.info("Order #%s step '%s' failed (attempt %s), retrying in %.1fs: %s",
                        order.id, event.event_type.value, event.retry_count, backoff_seconds, exc)

        db.commit()


async def run_worker_loop():
    logger.info("Queue worker %s started (poll interval: %ss)", WORKER_ID, settings.QUEUE_POLL_INTERVAL_SECONDS)
    while True:
        db = SessionLocal()
        try:
            event = _claim_next_event(db)
            if event:
                _process_event(db, event)
            else:
                await asyncio.sleep(settings.QUEUE_POLL_INTERVAL_SECONDS)
        except Exception:  # noqa: BLE001
            logger.exception("Worker loop error")
            await asyncio.sleep(settings.QUEUE_POLL_INTERVAL_SECONDS)
        finally:
            db.close()