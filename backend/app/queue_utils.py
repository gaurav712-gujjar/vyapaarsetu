from sqlalchemy.orm import Session

from .models import EventQueue, EventTypeEnum, Order, OrderStatusEnum

# The three-step pipeline every order goes through, in order.
PIPELINE_STEPS = [
    EventTypeEnum.verify_payment,
    EventTypeEnum.update_inventory,
    EventTypeEnum.send_confirmation,
]


def enqueue_order_pipeline(db: Session, order: Order) -> None:
    """Push the standard processing pipeline for an order onto the event_queue table
    and flip the order into 'queued'. Idempotent: if events already exist for this
    order, does nothing (prevents duplicate enqueue on retried requests)."""
    existing = db.query(EventQueue).filter(EventQueue.order_id == order.id).first()
    if existing:
        return

    for step in PIPELINE_STEPS:
        db.add(EventQueue(order_id=order.id, event_type=step, payload={}))

    order.status = OrderStatusEnum.queued
    db.commit()
