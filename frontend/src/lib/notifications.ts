/**
 * In-app notifications — the header bell and the reminder strip on the Series page.
 *
 * Mirrors `backend/app/schemas/notification.py`. Reminders are raised by the server when
 * the list is read (there is no scheduler), so polling this endpoint is also what keeps
 * them current.
 */
import api from "@/lib/api";

export type AppNotification = {
  id: number;
  category: string;
  kind: string;
  severity: "info" | "success" | "warning" | "critical";
  title: string;
  body?: string | null;
  link?: string | null;
  due_date?: string | null;
  created_at?: string | null;
  read: boolean;
};

export type NotificationList = { items: AppNotification[]; unread_count: number };

/** Fired after anything marks notifications read, so the bell and the page strip agree. */
export const NOTIFICATIONS_CHANGED = "notifications:changed";

export const fetchNotifications = async (params: {
  category?: string;
  unread_only?: boolean;
  limit?: number;
} = {}) => (await api.get<NotificationList>("/notifications/", { params })).data;

export const markNotificationsRead = async (ids?: number[], category?: string) => {
  await api.post("/notifications/read", { ids: ids ?? null, category: category ?? null });
  if (typeof window !== "undefined") window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED));
};

export const SEVERITY_STYLE: Record<string, { dot: string; chip: string }> = {
  critical: { dot: "bg-red-500", chip: "bg-red-50 text-red-700 border-red-200" },
  warning: { dot: "bg-amber-500", chip: "bg-amber-50 text-amber-700 border-amber-200" },
  success: { dot: "bg-emerald-500", chip: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  info: { dot: "bg-blue-500", chip: "bg-blue-50 text-blue-700 border-blue-200" },
};

/** "5m ago", "3h ago", "2d ago" — for when a notification was raised. */
export function ago(iso?: string | null): string {
  if (!iso) return "";
  // The server writes naive UTC.
  const then = new Date(iso.endsWith("Z") ? iso : `${iso}Z`).getTime();
  const mins = Math.max(0, Math.round((Date.now() - then) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}
