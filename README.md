# VyapaarSetu

**Multi-channel commerce orchestration engine for Indian small businesses** — a storefront,
a WhatsApp/Instagram chat-commerce bot, Razorpay payments, and an owner dashboard, all
sharing one order pipeline.

---

## 1. Why we built this

Most small D2C sellers in India — clothing, sweets, home-cooked food, handicrafts — don't
run a "website business." They run a **WhatsApp business**. Customers browse a catalogue
sent as chat messages, ask "yeh available hai kya," pay via a UPI link, and expect a reply
the moment the payment goes through. Meanwhile the same seller might also have a small
website, and definitely wants one place to see every order, refund, and stock number —
not three different tools that don't talk to each other.

Existing options don't fit this middle ground:
- Full e-commerce platforms (Shopify-class) assume a website-first business and treat
  WhatsApp as an afterthought integration, if at all.
- Plain WhatsApp Business App has no inventory, no payment reconciliation, and no order
  history — just a chat window.
- Hiring someone to reply to every "order karna hai" message doesn't scale past a
  handful of orders a day, and mistakes (double-selling an out-of-stock item, forgetting
  to follow up on a failed payment) cost trust with repeat customers.

**VyapaarSetu's purpose** is to give a small seller one backend that treats a WhatsApp
message, an Instagram DM, and a website checkout as three doors into the *same* order
system — same stock, same payment verification, same retry/refund safety net, same
dashboard — so the owner never has to reconcile things by hand across tools.

## 2. Real-world application

- **A sweet shop owner** posts a WhatsApp catalogue link. A customer chats "Badam Halwa
  500g bhejo," the bot shows matching in-stock items, takes the order, sends a Razorpay
  payment link, and confirms the order back on WhatsApp the moment payment clears —
  no human in the loop for a routine order.
- **The same shop's website** shares the identical product/stock database, so a sale
  made via WhatsApp is instantly reflected as reduced stock on the website, and vice
  versa — no overselling the last box of ladoo twice.
- **A payment fails partway** (bank timeout, customer closes the tab) — the system
  doesn't just leave the customer wondering. It automatically re-checks with Razorpay,
  and either confirms the order or honestly tells the customer nothing was charged.
  If something breaks *after* a successful payment (e.g. stock ran out in the few
  seconds between "order confirmed" and inventory update), the system auto-refunds and
  reassures the customer, and flags the order for the owner to review.
- **The owner** logs into a dashboard (not visible or reachable by customers) to see
  live order counts, a dead-letter queue of anything that needed manual attention, and
  can requeue a stuck order with one click.

## 3. High-level architecture

```
                         ┌─────────────────────────────────────────────┐
                         │                  CHANNELS                   │
                         │                                              │
                         │   Website          WhatsApp        Instagram │
                         │  (React SPA)      (Meta Cloud API)  (Meta DM)│
                         └──────┬────────────────┬────────────────┬────┘
                                │                 │                │
                     REST calls │        webhook  │        webhook │
                     (checkout, │        POST      │        POST    │
                     products)  │                 │                │
                                ▼                 ▼                ▼
                    ┌────────────────┐   ┌──────────────────────────────┐
                    │  /api/orders   │   │   /api/webhooks/meta/*       │
                    │  /api/products │   │   (meta_webhooks.py)         │
                    │  (routers/)    │   │            │                 │
                    └───────┬────────┘   │            ▼                 │
                            │            │   conversation.py            │
                            │            │   (chat-commerce state       │
                            │            │    machine: browse → cart →  │
                            │            │    pay → confirm)            │
                            │            │            │                 │
                            │            │            ▼                 │
                            │            │        llm.py                │
                            │            │  (Groq/Llama intent parser:  │
                            │            │   "what did the customer     │
                            │            │    mean?" -> structured JSON)│
                            │            └────────────┬─────────────────┘
                            │                          │
                            ▼                          ▼
                 ┌───────────────────────────────────────────────┐
                 │              FastAPI application               │
                 │  ┌───────────┐  ┌────────────┐  ┌────────────┐ │
                 │  │  security │  │   deps     │  │  messaging │ │
                 │  │  (JWT,    │  │ (require_  │  │ (send WA / │ │
                 │  │  bcrypt)  │  │  admin)    │  │  IG replies│ │
                 │  └───────────┘  └────────────┘  └────────────┘ │
                 └───────────────────────┬─────────────────────────┘
                                          ▼
                          ┌───────────────────────────────┐
                          │        MySQL database          │
                          │  users, categories, products,  │
                          │  orders, order_items,          │
                          │  conversation_states,          │
                          │  event_queue, dlq_items         │
                          └───────────────┬─────────────────┘
                                          ▲  │
                     writes 3 pipeline    │  │ polls (SELECT ... FOR
                     steps per order      │  │ UPDATE SKIP LOCKED)
                                          │  ▼
                          ┌───────────────────────────────┐
                          │   workers/queue_worker.py       │
                          │  verify_payment -> update_      │
                          │  inventory -> send_confirmation │
                          │  (retry w/ backoff, DLQ after    │
                          │   MAX_RETRIES)                   │
                          └───────────────┬───────────────┘
                                          │
                                          ▼
                          ┌───────────────────────────────┐
                          │           Razorpay               │
                          │  Payment Links (chat) / Orders   │
                          │  API (website) + webhook events  │
                          │  (razorpay_webhooks.py)          │
                          └───────────────────────────────┘
```

## 4. Folder / file guide

### `backend/app/` — core application

| File | What it does |
|---|---|
| `main.py` | FastAPI app entrypoint. Wires up all routers, creates DB tables + seed data + admin user on first boot, and starts the queue worker as a background `asyncio` task alongside the API. |
| `config.py` | All environment-driven settings (DB credentials, JWT secret, Razorpay keys, Meta/WhatsApp tokens, Groq key) via Pydantic `Settings`, loaded from `.env`. |
| `database.py` | SQLAlchemy engine/session setup (`SessionLocal`, `get_db` dependency). |
| `models.py` | All ORM tables: `User`, `Category`, `Product`, `Order`, `OrderItem`, `EventQueue`, `DlqItem`, `ConversationState`, plus the enums used across the app (order status, payment status, channel, etc). |
| `schemas.py` | Pydantic request/response models for the REST API (checkout, login, product CRUD, dashboard stats). |
| `security.py` | Password hashing (bcrypt) and JWT issue/verify for admin login. |
| `deps.py` | FastAPI dependency for `require_admin` — decodes the JWT and 403s anyone who isn't `role=admin`, gating every dashboard route. |
| `queue_utils.py` | `enqueue_order_pipeline()` — idempotently writes the 3-step job pipeline (`verify_payment`, `update_inventory`, `send_confirmation`) into `event_queue` for a given order. |
| `messaging.py` | Sends outbound WhatsApp/Instagram messages (text + image) via the Meta Graph API. Falls back to logging if Meta credentials aren't configured yet, so local dev doesn't need real WhatsApp access. |
| `conversation.py` | The chat-commerce brain. Owns the WhatsApp/Instagram conversation state machine (new → browsing → awaiting_payment → completed), builds the catalogue/category messages, matches customer text to real products, creates orders + Razorpay Payment Links, describes order status back to the customer, and handles the "payment failed" / "refund and reassure" customer messaging. |
| `llm.py` | Calls Groq's Llama model to turn a free-text WhatsApp/Instagram message into structured intent (`browse_categories`, `select_item`, `confirm_order`, `order_status`, etc) that `conversation.py` acts on. Has a safe fallback if the LLM call fails, so the bot never goes silent. |

### `backend/app/routers/` — HTTP endpoints

| File | What it does |
|---|---|
| `auth.py` | `POST /api/auth/login` — issues a JWT for the admin dashboard. |
| `products.py` | Public `GET /api/categories`, `GET /api/products` (storefront catalogue) plus admin-only product create/update. |
| `orders.py` | Website checkout flow: `POST /api/orders/checkout` (creates order + Razorpay order/link), payment verification and retry endpoints. |
| `webhooks.py` | Generic normalized webhook endpoint (`/api/webhooks/{channel}`) for any channel that can POST a simple JSON payload (delivery partners, manual testing) — shares idempotency/enqueue logic with the real Meta adapter. |
| `meta_webhooks.py` | The real Meta Cloud API adapter for WhatsApp and Instagram — verification handshake, signature check, and translating Meta's nested payload into a call to `conversation.handle_inbound_message()`. |
| `razorpay_webhooks.py` | Receives Razorpay's server-to-server events (`payment_link.paid`, `.expired`, `.cancelled`) for the chat-commerce payment-link flow, and is the source of truth for marking a chat order paid. |
| `dashboard.py` | Admin-only (`require_admin`-gated) endpoints: live stats, order list, DLQ list + requeue action. |

### `backend/app/workers/`

| File | What it does |
|---|---|
| `queue_worker.py` | The MySQL-backed job processor. Polls `event_queue` with `SELECT ... FOR UPDATE SKIP LOCKED` (safe for multiple worker processes), runs each pipeline step in order per order, retries failures with exponential backoff, and moves permanently-failed steps to `dlq_items` while triggering the correct customer message (refund+reassure, or honest payment-failed) depending on whether money was actually taken. |

### `backend/` — top level

| File | What it does |
|---|---|
| `schema.sql` | Raw SQL schema (mirrors `models.py`) for setting up MySQL by hand instead of relying on SQLAlchemy's auto-create. |
| `requirements.txt` | Python dependencies. |
| `.env` / `.env.example` | Environment configuration (never commit real secrets). |

### `frontend/src/` — React storefront + admin

| File | What it does |
|---|---|
| `main.jsx` / `App.jsx` | App bootstrap and route table (storefront, checkout, order status, admin login, admin dashboard). |
| `api.js` | Thin fetch wrapper for calling the backend REST API. |
| `auth.js` | Stores/reads the admin JWT and exposes login state to route guards. |
| `pages/Storefront.jsx` | Public product browsing + add-to-cart. |
| `pages/Checkout.jsx` | Cart review + Razorpay checkout popup integration. |
| `pages/OrderStatus.jsx` | Customer-facing order lookup/status page. |
| `pages/AdminLogin.jsx` | Admin JWT login form. |
| `pages/AdminDashboard.jsx` | Owner-only dashboard: stats, order list, DLQ + requeue. |
| `components/ProductCard.jsx`, `Navbar.jsx`, `ProtectedRoute.jsx` | Shared UI pieces; `ProtectedRoute` blocks unauthenticated access to `/admin/*` on the frontend (the real enforcement is still backend-side `require_admin`). |

## 5. Workflow overview

### 5.1 Chat-commerce order (WhatsApp / Instagram)

1. Customer messages the business's WhatsApp/Instagram number.
2. Meta POSTs the event to `meta_webhooks.py`, which extracts the sender + text and calls
   `conversation.handle_inbound_message()`.
3. `conversation.py` loads (or creates) that customer's `ConversationState`, then calls
   `llm.py` to classify the message against the live catalogue and current cart/state.
4. Based on intent, `conversation.py` replies via `messaging.py`: category list → items in
   a category (with images) → add to cart → create an `Order` + Razorpay Payment Link on
   "confirm."
5. Customer pays on Razorpay's page and is redirected back into the WhatsApp chat.
6. Razorpay calls `razorpay_webhooks.py` with `payment_link.paid`, which marks the order
   paid and calls `enqueue_order_pipeline()`.
7. `queue_worker.py` picks up the 3 pipeline steps in order, verifies payment, decrements
   stock, and sends the "order confirmed" WhatsApp message.
8. If a step fails permanently after payment succeeded, the customer is refunded and told
   so directly, honestly and without alarm; if payment itself never completed, the
   customer is told plainly that nothing was charged and invited to try again.

### 5.2 Website order

1. Customer checks out on the storefront → `POST /api/orders/checkout` creates the
   `Order`/`OrderItem` rows and a Razorpay order.
2. Frontend opens the Razorpay checkout popup; on success it calls
   `/api/orders/verify-payment`, which signature-verifies the payment and calls
   `enqueue_order_pipeline()` — same shared pipeline as the chat-commerce flow from here on.

### 5.3 Owner operations

The dashboard (`AdminDashboard.jsx` → `dashboard.py`, JWT-gated via `require_admin`) shows
live order counts, the current DLQ (orders where a pipeline step failed permanently), and
lets the owner requeue a DLQ'd order after fixing the underlying issue (e.g. restocking).

## 6. Setup

- **Backend:** `cd backend`, create a venv, `pip install -r requirements.txt`, copy
  `.env.example` to `.env` and fill in your MySQL + Razorpay + Meta/Groq credentials, then
  `uvicorn app.main:app --reload --port 8000` (the queue worker starts automatically with
  the API). First boot creates tables, seed categories, and your admin user.
- **Frontend:** `cd frontend`, `npm install`, copy `.env.example` to `.env`, `npm run dev`.
- **Real channels:** point Meta's WhatsApp/Instagram Cloud API webhook at
  `/api/webhooks/meta/whatsapp` and `/api/webhooks/meta/instagram`, and configure a
  Razorpay Dashboard webhook (Payment Links events) pointing at `/api/webhooks/razorpay`.