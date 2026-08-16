import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";

function loadRazorpayScript() {
  return new Promise((resolve) => {
    if (window.Razorpay) return resolve(true);
    const script = document.createElement("script");
    script.src = "https://checkout.razorpay.com/v1/checkout.js";
    script.onload = () => resolve(true);
    script.onerror = () => resolve(false);
    document.body.appendChild(script);
  });
}

export default function Checkout({ cart, updateQty, removeItem, clearCart }) {
  const navigate = useNavigate();
  const [form, setForm] = useState({ customer_name: "", customer_phone: "", customer_email: "", customer_address: "" });
  const [status, setStatus] = useState("idle"); // idle | paying | error
  const [error, setError] = useState(null);

  const total = cart.reduce((sum, i) => sum + i.price * i.quantity, 0);

  const handlePay = async (e) => {
    e.preventDefault();
    setError(null);

    if (cart.length === 0) {
      setError("Your cart is empty.");
      return;
    }

    setStatus("paying");
    try {
      const checkoutRes = await api.checkout({
        ...form,
        items: cart.map((i) => ({ product_id: i.id, quantity: i.quantity })),
      });

      const scriptLoaded = await loadRazorpayScript();
      if (!scriptLoaded) throw new Error("Could not load Razorpay checkout. Check your connection.");

      const rzp = new window.Razorpay({
        key: checkoutRes.razorpay_key_id,
        amount: checkoutRes.amount_paise,
        currency: checkoutRes.currency,
        name: "VyapaarSetu",
        description: `Order #${checkoutRes.order_id}`,
        order_id: checkoutRes.razorpay_order_id,
        prefill: {
          name: form.customer_name,
          email: form.customer_email,
          contact: form.customer_phone,
        },
        handler: async (response) => {
          try {
            await api.verifyPayment({
              order_id: checkoutRes.order_id,
              razorpay_order_id: response.razorpay_order_id,
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_signature: response.razorpay_signature,
            });
            clearCart();
            navigate(`/order/${checkoutRes.order_id}`);
          } catch (err) {
            setError(err.message);
            setStatus("error");
          }
        },
        modal: {
          ondismiss: async () => {
            // Customer closed the modal, possibly after a failed attempt --
            // ask the backend to double-check with Razorpay in the
            // background (it retries automatically) rather than assuming
            // the worst immediately.
            try {
              await api.paymentRetry(checkoutRes.order_id);
            } catch (_) { /* best-effort */ }
            setStatus("idle");
          },
        },
        theme: { color: "#22314F" },
      });

      rzp.on("payment.failed", async () => {
        try {
          await api.paymentRetry(checkoutRes.order_id);
        } catch (_) { /* best-effort */ }
        setStatus("error");
        setError(
          "That attempt didn't go through. We're double-checking with the payment provider in the " +
          "background — if any amount was deducted, it will be automatically refunded. Feel free to try again."
        );
      });

      rzp.open();
    } catch (err) {
      setError(err.message);
      setStatus("error");
    }
  };

  return (
    <div className="vs-checkout">
      <section className="vs-cart">
        <h2>Your cart</h2>
        {cart.length === 0 ? (
          <p className="vs-muted">Nothing here yet — go add something you'll love.</p>
        ) : (
          <ul className="vs-cart__list">
            {cart.map((item) => (
              <li key={item.id} className="vs-cart__item">
                <span className="vs-cart__name">{item.name}</span>
                <input
                  type="number"
                  min="1"
                  value={item.quantity}
                  onChange={(e) => updateQty(item.id, Number(e.target.value))}
                />
                <span>₹{(item.price * item.quantity).toFixed(0)}</span>
                <button className="vs-link" onClick={() => removeItem(item.id)}>Remove</button>
              </li>
            ))}
          </ul>
        )}
        <p className="vs-cart__total">Total: ₹{total.toFixed(0)}</p>
      </section>

      <form className="vs-form" onSubmit={handlePay}>
        <h2>Delivery details</h2>
        <label>
          Full name
          <input required value={form.customer_name}
            onChange={(e) => setForm({ ...form, customer_name: e.target.value })} />
        </label>
        <label>
          Phone
          <input required value={form.customer_phone}
            onChange={(e) => setForm({ ...form, customer_phone: e.target.value })} />
        </label>
        <label>
          Email (optional)
          <input type="email" value={form.customer_email}
            onChange={(e) => setForm({ ...form, customer_email: e.target.value })} />
        </label>
        <label>
          Delivery address
          <textarea required value={form.customer_address}
            onChange={(e) => setForm({ ...form, customer_address: e.target.value })} />
        </label>

        {error && <p className="vs-error">{error}</p>}

        <button type="submit" className="vs-btn vs-btn--accent" disabled={status === "paying"}>
          {status === "paying" ? "Opening payment…" : `Pay ₹${total.toFixed(0)} with Razorpay`}
        </button>
      </form>
    </div>
  );
}