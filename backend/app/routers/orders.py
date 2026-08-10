import uuid
import razorpay
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..config import settings
from ..models import Order, OrderItem, Product, ChannelEnum, OrderStatusEnum, PaymentStatusEnum
from ..schemas import CheckoutRequest, CheckoutResponse, PaymentVerifyRequest, OrderOut
from ..queue_utils import enqueue_order_pipeline

router = APIRouter(prefix="/api/orders", tags=["orders"])

razorpay_client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


@router.post("/checkout", response_model=CheckoutResponse)
def checkout(payload: CheckoutRequest, db: Session = Depends(get_db)):
    if not payload.items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    total = 0.0
    resolved_items = []
    for item in payload.items:
        product = db.query(Product).filter(Product.id == item.product_id, Product.is_active == True).first()  # noqa: E712
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")
        if product.stock < item.quantity:
            raise HTTPException(status_code=400, detail=f"'{product.name}' is out of stock")
        total += float(product.price) * item.quantity
        resolved_items.append((product, item.quantity))

    idempotency_key = f"website:{uuid.uuid4()}"
    order = Order(
        idempotency_key=idempotency_key,
        channel=ChannelEnum.website,
        customer_name=payload.customer_name,
        customer_phone=payload.customer_phone,
        customer_email=payload.customer_email,
        customer_address=payload.customer_address,
        total_amount=total,
        status=OrderStatusEnum.pending,
        payment_status=PaymentStatusEnum.not_initiated,
        raw_payload=payload.dict(),
    )
    db.add(order)
    db.flush()  # get order.id before commit

    for product, qty in resolved_items:
        db.add(OrderItem(order_id=order.id, product_id=product.id, quantity=qty, unit_price=product.price))

    # Create the Razorpay order (amount is in paise)
    amount_paise = int(round(total * 100))
    try:
        rp_order = razorpay_client.order.create({
            "amount": amount_paise,
            "currency": "INR",
            "receipt": f"order_{order.id}",
            "payment_capture": 1,
        })
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=f"Razorpay order creation failed: {exc}")

    order.razorpay_order_id = rp_order["id"]
    order.payment_status = PaymentStatusEnum.created
    db.commit()

    return CheckoutResponse(
        order_id=order.id,
        razorpay_order_id=rp_order["id"],
        razorpay_key_id=settings.RAZORPAY_KEY_ID,
        amount_paise=amount_paise,
    )


@router.post("/verify-payment", response_model=OrderOut)
def verify_payment(payload: PaymentVerifyRequest, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == payload.order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.razorpay_order_id != payload.razorpay_order_id:
        raise HTTPException(status_code=400, detail="Order mismatch")

    try:
        razorpay_client.utility.verify_payment_signature({
            "razorpay_order_id": payload.razorpay_order_id,
            "razorpay_payment_id": payload.razorpay_payment_id,
            "razorpay_signature": payload.razorpay_signature,
        })
    except razorpay.errors.SignatureVerificationError:
        order.payment_status = PaymentStatusEnum.failed
        order.status = OrderStatusEnum.failed
        db.commit()
        raise HTTPException(status_code=400, detail="Payment signature verification failed")

    order.razorpay_payment_id = payload.razorpay_payment_id
    order.razorpay_signature = payload.razorpay_signature
    order.payment_status = PaymentStatusEnum.paid
    db.commit()

    enqueue_order_pipeline(db, order)
    db.refresh(order)
    return order


@router.get("/{order_id}", response_model=OrderOut)
def get_order(order_id: int, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order
