import { Navigate } from "react-router-dom";
import { auth } from "../auth";

export default function ProtectedRoute({ children }) {
  if (!auth.isAdmin()) {
    return <Navigate to="/admin/login" replace />;
  }
  return children;
}
