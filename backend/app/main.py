import asyncio
import logging
import contextlib

import anyio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine, SessionLocal
from .config import settings
from .security import hash_password
from .models import User, RoleEnum, Category
from .workers.queue_worker import run_worker_loop

from .routers import auth, products, orders, webhooks, dashboard, meta_webhooks, razorpay_webhooks

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vyapaarsetu")

worker_task: asyncio.Task | None = None


def bootstrap_admin_and_categories():
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.email == settings.ADMIN_EMAIL).first()
        if not admin:
            db.add(User(
                name="Store Owner",
                email=settings.ADMIN_EMAIL,
                password_hash=hash_password(settings.ADMIN_PASSWORD),
                role=RoleEnum.admin,
            ))
            logger.info("Bootstrapped admin account: %s", settings.ADMIN_EMAIL)

        if db.query(Category).count() == 0:
            defaults = ["Clothing", "Sweets", "Home-cooked Food", "Handicrafts"]
            for name in defaults:
                db.add(Category(name=name, slug=name.lower().replace(" ", "-").replace("--", "-")))
            logger.info("Seeded default categories")

        db.commit()
    finally:
        db.close()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    global worker_task
    # FastAPI runs sync (def, not async def) route handlers in a background
    # thread pool via anyio, which defaults to only 40 concurrent threads --
    # under load-test-scale concurrency this queues requests even though the
    # DB connection pool below has room. Raise it to match.
    anyio.to_thread.current_default_thread_limiter().total_tokens = 100

    Base.metadata.create_all(bind=engine)
    bootstrap_admin_and_categories()
    worker_task = asyncio.create_task(run_worker_loop())
    logger.info("VyapaarSetu backend ready")
    yield
    if worker_task:
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task


app = FastAPI(title="VyapaarSetu API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to your storefront domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(products.router)
app.include_router(orders.router)
app.include_router(webhooks.router)
app.include_router(dashboard.router)
app.include_router(meta_webhooks.router)
app.include_router(razorpay_webhooks.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}