from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel, EmailStr


# ---------- Auth ----------
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    name: str


# ---------- Categories / Products ----------
class CategoryOut(BaseModel):
    id: int
    name: str
    slug: str

    class Config:
        from_attributes = True


class ProductOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    price: float
    image_url: Optional[str] = None
    stock: int
    is_active: bool
    category: CategoryOut

    class Config:
        from_attributes = True


class ProductCreate(BaseModel):
    category_id: int
    name: str
    description: Optional[str] = None
    price: float
    image_url: Optional[str] = None
    stock: int = 0


# ---------- Orders / Checkout ----------
class CartItem(BaseModel):
    product_id: int
    quantity: int


class CheckoutRequest(BaseModel):
    customer_name: str
    customer_phone: str
    customer_email: Optional[EmailStr] = None
    customer_address: str
    items: List[CartItem]


class CheckoutResponse(BaseModel):
    order_id: int
    razorpay_order_id: str
    razorpay_key_id: str
    amount_paise: int
    currency: str = "INR"


class PaymentVerifyRequest(BaseModel):
    order_id: int
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class WebhookOrderPayload(BaseModel):
    """Generic payload accepted from external channels (WhatsApp, Instagram, delivery partner)."""
    channel_order_ref: str
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_address: Optional[str] = None
    raw_text: Optional[str] = None
    items: Optional[List[CartItem]] = None
    extra: Optional[Any] = None


class OrderOut(BaseModel):
    id: int
    channel: str
    customer_name: Optional[str]
    customer_phone: Optional[str]
    total_amount: float
    status: str
    payment_status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ---------- Dashboard ----------
class DashboardStats(BaseModel):
    total_orders: int
    pending: int
    queued: int
    processing: int
    confirmed: int
    failed: int
    flagged: int
    queue_pending: int
    queue_processing: int
    dlq_open: int
    total_retries: int
    revenue_confirmed: float
