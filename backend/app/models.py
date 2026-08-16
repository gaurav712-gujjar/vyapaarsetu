import enum
from sqlalchemy import (
    Column, BigInteger, Integer, String, Text, DECIMAL, Boolean,
    Enum, JSON, TIMESTAMP, ForeignKey, UniqueConstraint, func
)
from sqlalchemy.orm import relationship

from .database import Base


class RoleEnum(str, enum.Enum):
    admin = "admin"
    customer = "customer"


class ChannelEnum(str, enum.Enum):
    website = "website"
    whatsapp = "whatsapp"
    instagram = "instagram"
    delivery_partner = "delivery_partner"
    other = "other"


class OrderStatusEnum(str, enum.Enum):
    pending = "pending"
    queued = "queued"
    processing = "processing"
    payment_verified = "payment_verified"
    inventory_updated = "inventory_updated"
    confirmed = "confirmed"
    failed = "failed"
    flagged = "flagged"


class PaymentStatusEnum(str, enum.Enum):
    not_initiated = "not_initiated"
    created = "created"
    paid = "paid"
    failed = "failed"


class EventTypeEnum(str, enum.Enum):
    verify_payment = "verify_payment"
    update_inventory = "update_inventory"
    send_confirmation = "send_confirmation"
    retry_payment_check = "retry_payment_check"


class QueueStatusEnum(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    done = "done"
    failed = "failed"


class ConvStateEnum(str, enum.Enum):
    new = "new"
    browsing = "browsing"
    awaiting_payment = "awaiting_payment"
    completed = "completed"


class User(Base):
    __tablename__ = "users"
    id = Column(BigInteger, primary_key=True)
    name = Column(String(120), nullable=False)
    email = Column(String(190), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(Enum(RoleEnum), nullable=False, default=RoleEnum.customer)
    created_at = Column(TIMESTAMP, server_default=func.now())


class Category(Base):
    __tablename__ = "categories"
    id = Column(BigInteger, primary_key=True)
    name = Column(String(100), nullable=False)
    slug = Column(String(100), nullable=False, unique=True)
    products = relationship("Product", back_populates="category")


class Product(Base):
    __tablename__ = "products"
    id = Column(BigInteger, primary_key=True)
    category_id = Column(BigInteger, ForeignKey("categories.id"), nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    price = Column(DECIMAL(10, 2), nullable=False)
    image_url = Column(String(500))
    stock = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    category = relationship("Category", back_populates="products")


class Order(Base):
    __tablename__ = "orders"
    id = Column(BigInteger, primary_key=True)
    idempotency_key = Column(String(255), nullable=False, unique=True)
    channel = Column(Enum(ChannelEnum), nullable=False, default=ChannelEnum.website)
    customer_name = Column(String(150))
    customer_phone = Column(String(20))
    customer_email = Column(String(190))
    customer_address = Column(Text)
    total_amount = Column(DECIMAL(10, 2), nullable=False, default=0)
    status = Column(Enum(OrderStatusEnum), nullable=False, default=OrderStatusEnum.pending)
    payment_status = Column(Enum(PaymentStatusEnum), nullable=False, default=PaymentStatusEnum.not_initiated)
    razorpay_order_id = Column(String(100))
    razorpay_payment_id = Column(String(100))
    razorpay_signature = Column(String(255))
    raw_payload = Column(JSON)
    structured_data = Column(JSON)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    events = relationship("EventQueue", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(BigInteger, primary_key=True)
    order_id = Column(BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(BigInteger, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    unit_price = Column(DECIMAL(10, 2), nullable=False)

    order = relationship("Order", back_populates="items")
    product = relationship("Product")


class EventQueue(Base):
    __tablename__ = "event_queue"
    id = Column(BigInteger, primary_key=True)
    order_id = Column(BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(Enum(EventTypeEnum), nullable=False)
    payload = Column(JSON)
    status = Column(Enum(QueueStatusEnum), nullable=False, default=QueueStatusEnum.pending)
    retry_count = Column(Integer, nullable=False, default=0)
    next_retry_at = Column(TIMESTAMP, nullable=True)
    error_message = Column(Text)
    worker_id = Column(String(100))
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    order = relationship("Order", back_populates="events")


class DlqItem(Base):
    __tablename__ = "dlq_items"
    id = Column(BigInteger, primary_key=True)
    order_id = Column(BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    event_queue_id = Column(BigInteger, ForeignKey("event_queue.id"), nullable=False)
    failed_step = Column(String(100), nullable=False)
    error_message = Column(Text)
    retry_count = Column(Integer, nullable=False, default=0)
    resolved = Column(Boolean, nullable=False, default=False)
    created_at = Column(TIMESTAMP, server_default=func.now())


class ConversationState(Base):
    """Tracks where a WhatsApp/Instagram customer is in the chat-commerce
    flow: new -> browsing -> awaiting_payment -> completed. One row per
    (channel, external_id) -- external_id is the phone number for WhatsApp
    or the Instagram-scoped sender id."""
    __tablename__ = "conversation_states"
    __table_args__ = (UniqueConstraint("channel", "external_id", name="uq_conv_channel_external_id"),)

    id = Column(BigInteger, primary_key=True)
    channel = Column(Enum(ChannelEnum), nullable=False)
    external_id = Column(String(100), nullable=False)
    customer_name = Column(String(150))
    state = Column(Enum(ConvStateEnum), nullable=False, default=ConvStateEnum.new)
    cart = Column(JSON)  # {"product_id":.., "name":.., "price":.., "quantity":..}
    context = Column(JSON)  # {"category_id":.., "offset":..} -- category browsing/pagination, separate from cart
    pending_order_id = Column(BigInteger, ForeignKey("orders.id"), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())