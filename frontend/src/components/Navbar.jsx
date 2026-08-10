import { Link, useNavigate } from "react-router-dom";
import { auth } from "../auth";

export default function Navbar({ cartCount = 0 }) {
  const navigate = useNavigate();
  const isAdmin = auth.isAdmin();

  return (
    <header className="vs-nav">
      <Link to="/" className="vs-nav__brand">
        Vyapaar<span>Setu</span>
      </Link>
      <nav className="vs-nav__links">
        <Link to="/">Shop</Link>
        <Link to="/cart">Cart{cartCount > 0 ? ` (${cartCount})` : ""}</Link>
        {isAdmin ? (
          <>
            <Link to="/admin/dashboard">Dashboard</Link>
            <button
              className="vs-nav__logout"
              onClick={() => {
                auth.logout();
                navigate("/");
              }}
            >
              Log out
            </button>
          </>
        ) : (
          <Link to="/admin/login" className="vs-nav__owner">
            Owner login
          </Link>
        )}
      </nav>
    </header>
  );
}
