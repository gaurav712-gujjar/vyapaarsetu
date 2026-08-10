export default function ProductCard({ product, onAdd }) {
  return (
    <article className="vs-card">
      <div className="vs-card__image" style={{ backgroundImage: `url(${product.image_url || ""})` }}>
        {!product.image_url && <span className="vs-card__placeholder">{product.name[0]}</span>}
      </div>
      <div className="vs-card__body">
        <p className="vs-card__category">{product.category?.name}</p>
        <h3>{product.name}</h3>
        <p className="vs-card__desc">{product.description}</p>
        <div className="vs-card__footer">
          <span className="vs-card__price">₹{Number(product.price).toFixed(0)}</span>
          <button
            disabled={product.stock <= 0}
            onClick={() => onAdd(product)}
            className="vs-btn vs-btn--accent"
          >
            {product.stock > 0 ? "Add to cart" : "Out of stock"}
          </button>
        </div>
      </div>
    </article>
  );
}
