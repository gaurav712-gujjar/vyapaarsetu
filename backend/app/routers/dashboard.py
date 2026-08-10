from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_admin
from ..models import Order, OrderStatusEnum, EventQueue, QueueStatusEnum, DlqItem
from ..schemas import DashboardStats, OrderOut

router = APIRouter(prefix="/api/admin", tags=["admin-dashboard"])
# Every route below depends on require_admin -> regular customers get a 403.


@router.get("/stats", response_model=DashboardStats, dependencies=[Depends(require_admin)])
def get_stats(db: Session = Depends(get_db)):
    def count(status):
        return db.query(func.count(Order.id)).filter(Order.status == status).scalar()

    total_retries = db.query(func.coalesce(func.sum(EventQueue.retry_count), 0)).scalar()
    revenue = db.query(func.coalesce(func.sum(Order.total_amount), 0)).filter(
        Order.status == OrderStatusEnum.confirmed
    ).scalar()

    return DashboardStats(
        total_orders=db.query(func.count(Order.id)).scalar(),
        pending=count(OrderStatusEnum.pending),
        queued=count(OrderStatusEnum.queued),
        processing=count(OrderStatusEnum.processing),
        confirmed=count(OrderStatusEnum.confirmed),
        failed=count(OrderStatusEnum.failed),
        flagged=count(OrderStatusEnum.flagged),
        queue_pending=db.query(func.count(EventQueue.id)).filter(
            EventQueue.status == QueueStatusEnum.pending
        ).scalar(),
        queue_processing=db.query(func.count(EventQueue.id)).filter(
            EventQueue.status == QueueStatusEnum.processing
        ).scalar(),
        dlq_open=db.query(func.count(DlqItem.id)).filter(DlqItem.resolved == False).scalar(),  # noqa: E712
        total_retries=int(total_retries or 0),
        revenue_confirmed=float(revenue or 0),
    )


@router.get("/orders", response_model=List[OrderOut], dependencies=[Depends(require_admin)])
def list_orders(
    status: Optional[str] = None,
    channel: Optional[str] = None,
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
):
    q = db.query(Order)
    if status:
        q = q.filter(Order.status == status)
    if channel:
        q = q.filter(Order.channel == channel)
    return q.order_by(Order.id.desc()).limit(limit).all()


@router.get("/dlq", dependencies=[Depends(require_admin)])
def list_dlq(db: Session = Depends(get_db)):
    items = db.query(DlqItem).filter(DlqItem.resolved == False).order_by(DlqItem.id.desc()).all()  # noqa: E712
    return [
        {
            "id": i.id,
            "order_id": i.order_id,
            "failed_step": i.failed_step,
            "error_message": i.error_message,
            "retry_count": i.retry_count,
            "created_at": i.created_at,
        }
        for i in items
    ]


@router.post("/dlq/{dlq_id}/requeue", dependencies=[Depends(require_admin)])
def requeue_dlq_item(dlq_id: int, db: Session = Depends(get_db)):
    """Manually retry a dead-lettered step from the dashboard."""
    dlq_item = db.query(DlqItem).filter(DlqItem.id == dlq_id).first()
    if not dlq_item:
        return {"ok": False, "error": "Not found"}

    event = db.query(EventQueue).filter(EventQueue.id == dlq_item.event_queue_id).first()
    if event:
        event.status = QueueStatusEnum.pending
        event.retry_count = 0
        event.next_retry_at = None
        event.error_message = None
    dlq_item.resolved = True
    db.commit()
    return {"ok": True}
