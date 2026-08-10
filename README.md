# VyapaarSetu

Multi-channel order orchestration engine + storefront for a D2C seller (clothing, sweets,
home-cooked food, handicrafts), with Razorpay payments and an owner-only dashboard (RBAC).

## What's included

- **Backend** (`/backend`): FastAPI + MySQL. Public storefront APIs, checkout with Razorpay,
  a generic webhook endpoint for WhatsApp/Instagram/delivery-partner order ingestion,
  a MySQL-backed job queue with idempotency + retry/backoff + dead-letter queue, and
  an admin dashboard API protected by RBAC (JWT with `role=admin`).
- **Frontend** (`/frontend`): React (Vite) storefront with category browsing, cart, Razorpay
  checkout, order-status tracking, and an admin login + dashboard (only reachable with an
  admin JWT — regular customers never see it and the backend rejects non-admin tokens).

## How orders flow through the system

```
Website checkout ──┐
WhatsApp webhook ───┤
Instagram webhook ──┼──> /api/webhooks/{channel} or /api/orders/checkout
Delivery partner ───┘              │
                                    ▼
                      orders + order_items (MySQL)
                                    │
                    enqueue_order_pipeline() writes 3 rows
                       into event_queue: verify_payment,
                       update_inventory, send_confirmation
                                    │
                                    ▼
                  queue_worker.py polls event_queue (SELECT ... FOR
                  UPDATE SKIP LOCKED), runs each step, retries failed
                  steps with exponential backoff, and after MAX_RETRIES
                  moves the step into dlq_items + flags the order
                                    │
                                    ▼
                        Owner dashboard (RBAC-gated):
                     live counts, order list, DLQ + requeue button
```

**Idempotency:** every order has a unique `idempotency_key`. Webhook orders build it from
`{channel}:{channel_order_ref}` (the source platform's own message/order id), so a retried
webhook delivery returns the existing order instead of creating a duplicate. Website checkouts
get a fresh UUID per submission.

**RBAC:** `users.role` is `admin` or `customer`. Every `/api/admin/*` route depends on
`require_admin`, which decodes the JWT and returns `403` if the role isn't `admin`. The
frontend also hides the dashboard behind a route guard, but the real enforcement is on the
backend — someone can't get in by editing frontend code.

## 1. Backend setup

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # edit with your real MySQL + Razorpay credentials
```

Create the database (or let SQLAlchemy do it automatically on first run — see below):

```bash
mysql -u root -p < schema.sql
```

Edit `.env`:
- `DB_*` — your MySQL connection details
- `JWT_SECRET` — generate one with `openssl rand -hex 32`
- `ADMIN_EMAIL` / `ADMIN_PASSWORD` — your dashboard login, auto-created on first startup
- `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` — from your Razorpay dashboard (use test keys first)

Run the API (the background queue worker starts automatically with it):

```bash
uvicorn app.main:app --reload --port 8000
```

On first startup the app creates any missing tables, seeds the four categories, and creates
your admin user from `.env` — no manual SQL needed beyond having an empty database.

Add some products once it's running (via the admin API, using your admin token from
`/api/auth/login`):

```bash
curl -X POST http://localhost:8000/api/admin/products \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"category_id":1,"name":"Cotton Block-Print Kurta","price":899,"stock":20,"description":"Hand block-printed cotton kurta."}'
```

## 2. Frontend setup

```bash
cd frontend
npm install
cp .env.example .env   # set VITE_API_BASE_URL if backend isn't on localhost:8000
npm run dev
```

Visit `http://localhost:5173` for the storefront, `/admin/login` for the owner dashboard.

## 3. Wiring up real channels

The webhook endpoint `POST /api/webhooks/{whatsapp|instagram|delivery_partner}` expects a
normalized JSON body:

```json
{
  "channel_order_ref": "wamid.HBgL...",
  "customer_name": "Priya Sharma",
  "customer_phone": "+91...",
  "customer_address": "...",
  "raw_text": "send the same red kurta size M",
  "items": [{"product_id": 3, "quantity": 1}]
}
```

For real WhatsApp/Instagram integration, point Meta's Cloud API webhook at a small adapter
(or extend `webhooks.py` directly) that maps their payload shape into this format. For
free-text orders where `items` isn't resolvable yet, leave it empty and `raw_text` populated —
that's the hook point for adding an LLM-based parser before the pipeline runs.

## 4. Production notes

- Restrict CORS `allow_origins` in `app/main.py` to your real storefront domain.
- Run the queue worker as its own process for real horizontal scaling instead of the in-process
  `asyncio` task (the polling/locking logic in `queue_worker.py` already supports multiple
  worker processes safely).
- Put the API behind HTTPS and set a strong `JWT_SECRET` + admin password before going live.
- Switch Razorpay to live keys and add a server-side Razorpay webhook (in addition to the
  frontend-triggered `/api/orders/verify-payment`) for payments completed outside the checkout
  popup (e.g. UPI collect requests).
