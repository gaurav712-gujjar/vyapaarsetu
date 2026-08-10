"""
VyapaarSetu load test.

Run with:
    locust -f locustfile.py --host http://localhost:8000

Then open http://localhost:8089 in your browser, set number of users +
spawn rate, and click "Start swarming".

What this simulates:
- Most virtual users just browse (list categories, list products) --
  this is the read-heavy traffic a real storefront gets.
- A smaller fraction place orders via the WhatsApp webhook endpoint
  (mirrors real order volume, which is much lower than browsing volume).
  We use the webhook path instead of the website checkout flow because
  checkout requires a real Razorpay-signed payment, which can't be faked
  here without a real gateway round-trip.
"""
import random
import uuid

from locust import HttpUser, task, between


class StorefrontUser(HttpUser):
    wait_time = between(1, 3)  # seconds between tasks, mimics real browsing pace

    def on_start(self):
        # Cache the product list once per simulated user so order tasks
        # can pick a real product_id without hitting /api/products every time.
        resp = self.client.get("/api/products", name="/api/products")
        try:
            self.products = resp.json()
        except Exception:
            self.products = []

    @task(6)
    def browse_categories(self):
        self.client.get("/api/categories", name="/api/categories")

    @task(10)
    def browse_products(self):
        self.client.get("/api/products", name="/api/products")

    @task(2)
    def view_single_product_page_equivalent(self):
        # No single-product GET endpoint exists in this API, so this just
        # re-hits the list filtered client-side in the real frontend.
        # Included for weighting realism; safe to remove if not needed.
        self.client.get("/api/products", name="/api/products (detail view)")

    @task(1)
    def place_order_via_webhook(self):
        if not self.products:
            return
        product = random.choice(self.products)
        channel = random.choice(["whatsapp", "instagram", "delivery_partner"])
        payload = {
            "channel_order_ref": f"loadtest_{uuid.uuid4().hex[:12]}",
            "customer_name": "Load Test User",
            "customer_phone": f"+91{random.randint(7000000000, 9999999999)}",
            "customer_address": "Load test address, Jaipur",
            "raw_text": f"1 {product['name']}",
            "items": [{"product_id": product["id"], "quantity": 1}],
        }
        self.client.post(
            f"/api/webhooks/{channel}",
            json=payload,
            name="/api/webhooks/[channel]",
        )


class AdminUser(HttpUser):
    """A much smaller population simulating the shop owner checking the
    dashboard periodically while orders come in."""
    wait_time = between(5, 10)
    weight = 1  # relative to StorefrontUser's default weight of 1 -- set StorefrontUser.weight higher if desired

    def on_start(self):
        resp = self.client.post(
            "/api/auth/login",
            json={"email": "gaurav@gmail.com", "password": "Gaurav@712"},
            name="/api/auth/login",
        )
        try:
            self.token = resp.json().get("access_token")
        except Exception:
            self.token = None

    @task
    def check_dashboard(self):
        if not self.token:
            return
        headers = {"Authorization": f"Bearer {self.token}"}
        self.client.get("/api/admin/stats", headers=headers, name="/api/admin/stats")
        self.client.get("/api/admin/orders", headers=headers, name="/api/admin/orders")
        self.client.get("/api/admin/dlq", headers=headers, name="/api/admin/dlq")