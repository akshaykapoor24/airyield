import axios from "axios";
import { getToken, clearAuth } from "@/lib/auth";
import { markPlanBlocked } from "@/lib/planGate";

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1",
  headers: { "Content-Type": "application/json" },
});

api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  // For file uploads, drop the default application/json Content-Type so the
  // browser sets multipart/form-data with the correct boundary. Without this,
  // FormData posts go out as application/json and the server can't read the file.
  if (typeof FormData !== "undefined" && config.data instanceof FormData) {
    config.headers.delete("Content-Type");
  }
  return config;
});

// Endpoints that answer 401 as a normal outcome rather than "your session
// died". A failed login is the obvious one: nuking auth and hard-reloading
// there wipes the "Invalid email or password." message before it can be read.
const PUBLIC_AUTH_ROUTES =
  /\/auth\/(login|login-form|signup|register|verify-email|resend-verification|forgot-password|reset-password)$/;

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const url: string = err.config?.url ?? "";
    if (err.response?.status === 401 && !PUBLIC_AUTH_ROUTES.test(url)) {
      clearAuth();
      // Guard against a redirect loop when the 401 happened on /login itself.
      if (window.location.pathname !== "/login") window.location.href = "/login";
    }
    // 402 = the workspace has no active plan (get_current_user on the backend).
    // Deliberately NOT treated like 401: the session is perfectly valid, so
    // signing the user out would replace "here is who to email" with a login
    // form. Just raise the gate; the dashboard layout is subscribed to it.
    if (err.response?.status === 402) markPlanBlocked();
    return Promise.reject(err);
  }
);

export default api;
