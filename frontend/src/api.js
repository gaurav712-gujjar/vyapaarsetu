const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

function authHeaders() {
  const token = localStorage.getItem("vs_admin_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(options.headers || {}),
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${res.status})`);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  // Public storefront
  getCategories: () => request("/api/categories"),
  getProducts: (categorySlug) =>
    request(`/api/products${categorySlug ? `?category=${categorySlug}` : ""}`),

  // Checkout
  checkout: (payload) =>
    request("/api/orders/checkout", { method: "POST", body: JSON.stringify(payload) }),
  verifyPayment: (payload) =>
    request("/api/orders/verify-payment", { method: "POST", body: JSON.stringify(payload) }),
  getOrder: (orderId) => request(`/api/orders/${orderId}`),

  // Admin auth
  login: (email, password) =>
    request("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),

  // Admin dashboard (RBAC-protected on the backend)
  getStats: () => request("/api/admin/stats"),
  getAdminOrders: (params = "") => request(`/api/admin/orders${params}`),
  getDlq: () => request("/api/admin/dlq"),
  requeueDlq: (id) => request(`/api/admin/dlq/${id}/requeue`, { method: "POST" }),
  createProduct: (payload) =>
    request("/api/admin/products", { method: "POST", body: JSON.stringify(payload) }),
};
