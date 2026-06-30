import type { AppRole } from "@/lib/rbac";

const TOKEN_KEY = "ay_token";
const USER_KEY  = "ay_user";

export type AuthUser = {
  id: number;
  email: string;
  full_name: string;
  role: AppRole | string;
  department: string | null;
  is_active: boolean;
  tenant_id?: number | null;
  tenant_type?: "corporate" | "individual" | null;
};

export const ROLE_LABELS: Record<string, string> = {
  platform_admin:  "Platform Admin",
  super_admin:     "Super Admin",
  company_admin:   "Company Admin",
  operations_user: "Operations User",
  finance_user:    "Finance User",
  approver:        "Approver",
  viewer:          "View-only User",
};

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function getUser(): AuthUser | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function setUser(user: AuthUser) {
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export function isAuthenticated(): boolean {
  return !!getToken();
}
