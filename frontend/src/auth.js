export const auth = {
  setSession({ access_token, role, name }) {
    localStorage.setItem("vs_admin_token", access_token);
    localStorage.setItem("vs_admin_role", role);
    localStorage.setItem("vs_admin_name", name);
  },
  getToken: () => localStorage.getItem("vs_admin_token"),
  getRole: () => localStorage.getItem("vs_admin_role"),
  getName: () => localStorage.getItem("vs_admin_name"),
  isAdmin() {
    return !!this.getToken() && this.getRole() === "admin";
  },
  logout() {
    localStorage.removeItem("vs_admin_token");
    localStorage.removeItem("vs_admin_role");
    localStorage.removeItem("vs_admin_name");
  },
};
