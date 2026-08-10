import { useEffect, useState } from "react";
import { api } from "../api";
import ProductCard from "../components/ProductCard";

export default function Storefront({ onAddToCart }) {
  const [categories, setCategories] = useState([]);
  const [activeSlug, setActiveSlug] = useState(null);
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.getCategories().then(setCategories).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    setLoading(true);
    api
      .getProducts(activeSlug)
      .then(setProducts)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [activeSlug]);

  return (
    <div className="vs-storefront">
      <section className="vs-hero">
        <h1>Handmade, home-cooked, and homegrown — straight from India's makers.</h1>
        <p>Clothing, sweets, home-cooked food, and handicrafts from independent D2C sellers.</p>
      </section>

      <div className="vs-tabs">
        <button
          className={activeSlug === null ? "vs-tab vs-tab--active" : "vs-tab"}
          onClick={() => setActiveSlug(null)}
        >
          All
        </button>
        {categories.map((c) => (
          <button
            key={c.id}
            className={activeSlug === c.slug ? "vs-tab vs-tab--active" : "vs-tab"}
            onClick={() => setActiveSlug(c.slug)}
          >
            {c.name}
          </button>
        ))}
      </div>

      {error && <p className="vs-error">{error}</p>}
      {loading ? (
        <p className="vs-muted">Loading products…</p>
      ) : products.length === 0 ? (
        <p className="vs-muted">No products here yet — check back soon.</p>
      ) : (
        <div className="vs-grid">
          {products.map((p) => (
            <ProductCard key={p.id} product={p} onAdd={onAddToCart} />
          ))}
        </div>
      )}
    </div>
  );
}
