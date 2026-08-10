import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { auth } from "../auth";

export default function AdminLogin() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    try {
      const res = await api.login(email, password);
      if (res.role !== "admin") {
        setError("This account does not have dashboard access.");
        return;
      }
      auth.setSession(res);
      navigate("/admin/dashboard");
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="vs-admin-login">
      <form className="vs-form" onSubmit={handleSubmit}>
        <h2>Owner login</h2>
        <p className="vs-muted">This area is restricted to the store owner.</p>
        <label>
          Email
          <input required type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label>
          Password
          <input required type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {error && <p className="vs-error">{error}</p>}
        <button type="submit" className="vs-btn vs-btn--accent">Log in</button>
      </form>
    </div>
  );
}
