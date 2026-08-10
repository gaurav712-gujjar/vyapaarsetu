import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../api";

const STATUS_LABEL = {
  pending: "Received",
  queued: "In queue",
  processing: "Processing",
  payment_verified: "Payment confirmed",
  inventory_updated: "Preparing your order",
  confirmed: "Confirmed",
  failed: "Failed",
  flagged: "Under review",
};

export default function OrderStatus() {
  const { orderId } = useParams();
  const [order, setOrder] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchOrder = () => api.getOrder(orderId).then(setOrder).catch((e) => setError(e.message));
    fetchOrder();
    const interval = setInterval(fetchOrder, 4000);
    return () => clearInterval(interval);
  }, [orderId]);

  if (error) return <p className="vs-error">{error}</p>;
  if (!order) return <p className="vs-muted">Loading order…</p>;

  return (
    <div className="vs-order-status">
      <h1>Thank you, {order.customer_name || "friend"}!</h1>
      <p className="vs-muted">Order #{order.id}</p>
      <div className="vs-status-badge">{STATUS_LABEL[order.status] || order.status}</div>
      <p>Payment: {order.payment_status}</p>
      <p>Total: ₹{Number(order.total_amount).toFixed(0)}</p>
      <Link to="/" className="vs-link">Continue shopping</Link>
    </div>
  );
}
