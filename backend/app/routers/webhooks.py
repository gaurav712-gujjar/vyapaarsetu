from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Order, OrderItem, Product, ChannelEnum, OrderStatusEnum, PaymentStatusEnum
from ..schemas import WebhookOrderPayload, OrderOut
from ..queue_utils import enqueue_order_pipeline

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

VALID_CHANNELS = {"whatsapp", "instagram", "delivery_partner"}


def create_order_from_channel(db: Session, channel: str, payload: WebhookOrderPayload) -> Order:
    """
    Shared order-ingestion logic used by both the generic manual-test endpoint
    below and the real Meta webhook adapter (meta_webhooks.py). Handles
    idempotency, item resolution, and enqueuing the processing pipeline.
    """
    if channel not in VALID_CHANNELS:
        raise HTTPException(status_code=400, detail=f"Unknown channel '{channel}'")

    idempotency_key = f"{channel}:{payload.channel_order_ref}"

    # Idempotency: if we've already ingested this exact source event, return the
    # existing order instead of creating a duplicate.
    existing = db.query(Order).filter(Order.idempotency_key == idempotency_key).first()
    if existing:
        return existing

    total = 0.0
    resolved_items = []
    if payload.items:
        for item in payload.items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if not product:
                continue
            total += float(product.price) * item.quantity
            resolved_items.append((product, item.quantity))

    order = Order(
        idempotency_key=idempotency_key,
        channel=ChannelEnum(channel),
        customer_name=payload.customer_name,
        customer_phone=payload.customer_phone,
        customer_address=payload.customer_address,
        total_amount=total,
        status=OrderStatusEnum.pending,
        payment_status=PaymentStatusEnum.not_initiated,
        raw_payload=payload.dict(),
        # If items couldn't be resolved from clean data, structured_data stays
        # empty and this is where a free-text parser (e.g. an LLM) would fill
        # in the parsed item list before the pipeline runs.
        structured_data={"raw_text": payload.raw_text} if payload.raw_text else None,
    )

    try:
        db.add(order)
        db.flush()
        for product, qty in resolved_items:
            db.add(OrderItem(order_id=order.id, product_id=product.id, quantity=qty, unit_price=product.price))
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(Order).filter(Order.idempotency_key == idempotency_key).first()
        if existing:
            return existing
        raise HTTPException(status_code=409, detail="Duplicate event")

    # Non-website orders (COD / pre-arranged payment) go straight into the pipeline;
    # the worker's verify_payment step handles channel-specific confirmation.
    enqueue_order_pipeline(db, order)
    db.refresh(order)
    return order


@router.post("/{channel}", response_model=OrderOut)
def receive_channel_order(
    channel: str = Path(..., description="whatsapp | instagram | delivery_partner"),
    payload: WebhookOrderPayload = ...,
    db: Session = Depends(get_db),
):
    """
    Manual/test ingestion point -- accepts an already-normalized payload directly.
    Useful for curl/PowerShell testing and for delivery-partner APIs that already
    send clean JSON. Real WhatsApp/Instagram traffic from Meta does NOT come in
    this shape -- see meta_webhooks.py, which adapts Meta's raw payload into this
    same normalized format and calls create_order_from_channel().
    """
    return create_order_from_channel(db, channel, payload)