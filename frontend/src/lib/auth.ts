import type { AppRole } from "@/lib/rbac";
import { clearPlanBlocked } from "@/lib/planGate";

const TOKEN_KEY = "ay_token";
const USER_KEY  = "ay_user";

export type PlanStatus = "free" | "trial" | "active" | "expired" | "suspended";

export type AuthUser = {
  id: number;
  email: string;
  full_name: string;
  role: AppRole | string;
  department: string | null;
  is_active: boolean;
  is_verified?: boolean;
  onboarding_complete?: boolean;
  tenant_id?: number | null;
  tenant_type?: "corporate" | "individual" | null;
  // Subscription state of the user's workspace. Optional because a session that
  // signed in before this shipped has an ay_user without them — the dashboard
  // layout refetches /users/me on mount to heal that, and the 402 interceptor
  // catches whatever slips through.
  plan_active?: boolean;
  plan_status?: PlanStatus | string | null;
  plan_expires_at?: string | null;
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
  // Otherwise the next person to sign in on this tab inherits the previous
  // account's frozen state until their first request.
  clearPlanBlocked();
}

export function isAuthenticated(): boolean {
  return !!getToken();
}
