import { useEffect, useState } from "react";
import { api } from "../api";
import { auth } from "../auth";

const STAT_CARDS = [
  { key: "total_orders", label: "Total orders" },
  { key: "pending", label: "Pending" },
  { key: "queued", label: "Queued" },
  { key: "processing", label: "Processing" },
  { key: "confirmed", label: "Confirmed" },
  { key: "failed", label: "Failed" },
  { key: "flagged", label: "Flagged for review" },
  { key: "queue_pending", label: "Queue depth" },
  { key: "total_retries", label: "Total retries" },
  { key: "dlq_open", label: "Dead-letter items" },
];

export default function AdminDashboard() {
  const [stats, setStats] = useState(null);
  const [orders, setOrders] = useState([]);
  const [dlq, setDlq] = useState([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [error, setError] = useState(null);

  const load = () => {
    api.getStats().then(setStats).catch((e) => setError(e.message));
    api
      .getAdminOrders(statusFilter ? `?status=${statusFilter}` : "")
      .then(setOrders)
      .catch((e) => setError(e.message));
    api.getDlq().then(setDlq).catch((e) => setError(e.message));
  };

  useEffect(() => {
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter]);

  const handleRequeue = async (id) => {
    await api.requeueDlq(id);
    load();
  };

  return (
    <div className="vs-dashboard">
      <div className="vs-dashboard__header">
        <h1>Owner dashboard</h1>
        <span className="vs-muted">Signed in as {auth.getName()}</span>
      </div>

      {error && <p className="vs-error">{error}</p>}

      <div className="vs-stats-grid">
        {STAT_CARDS.map((card) => (
          <div key={card.key} className="vs-stat-card">
            <span className="vs-stat-card__value">{stats ? stats[card.key] : "—"}</span>
            <span className="vs-stat-card__label">{card.label}</span>
          </div>
        ))}
        <div className="vs-stat-card vs-stat-card--accent">
          <span className="vs-stat-card__value">
            ₹{stats ? Number(stats.revenue_confirmed).toFixed(0) : "—"}
          </span>
          <span className="vs-stat-card__label">Confirmed revenue</span>
        </div>
      </div>

      <section className="vs-panel">
        <div className="vs-panel__header">
          <h2>Orders</h2>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">All statuses</option>
            <option value="pending">Pending</option>
            <option value="queued">Queued</option>
            <option value="processing">Processing</option>
            <option value="confirmed">Confirmed</option>
            <option value="failed">Failed</option>
            <option value="flagged">Flagged</option>
          </select>
        </div>
        <table className="vs-table">
          <thead>
            <tr>
              <th>#</th><th>Channel</th><th>Customer</th><th>Total</th>
              <th>Status</th><th>Payment</th><th>Updated</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.id}>
                <td>{o.id}</td>
                <td>{o.channel}</td>
                <td>{o.customer_name || "—"}</td>
                <td>₹{Number(o.total_amount).toFixed(0)}</td>
                <td><span className={`vs-pill vs-pill--${o.status}`}>{o.status}</span></td>
                <td>{o.payment_status}</td>
                <td>{new Date(o.updated_at).toLocaleString()}</td>
              </tr>
            ))}
            {orders.length === 0 && (
              <tr><td colSpan={7} className="vs-muted">No orders match this filter.</td></tr>
            )}
          </tbody>
        </table>
      </section>

      <section className="vs-panel">
        <div className="vs-panel__header">
          <h2>Dead-letter queue</h2>
          <span className="vs-muted">Steps that failed after every retry</span>
        </div>
        <table className="vs-table">
          <thead>
            <tr><th>#</th><th>Order</th><th>Failed step</th><th>Error</th><th>Retries</th><th></th></tr>
          </thead>
          <tbody>
            {dlq.map((d) => (
              <tr key={d.id}>
                <td>{d.id}</td>
                <td>{d.order_id}</td>
                <td>{d.failed_step}</td>
                <td className="vs-error-cell">{d.error_message}</td>
                <td>{d.retry_count}</td>
                <td><button className="vs-link" onClick={() => handleRequeue(d.id)}>Requeue</button></td>
              </tr>
            ))}
            {dlq.length === 0 && (
              <tr><td colSpan={6} className="vs-muted">Nothing here — all steps are healthy.</td></tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}
