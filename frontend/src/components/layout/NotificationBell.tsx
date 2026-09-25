"use client";

/**
 * The header bell: unread count, and a panel of the latest notifications.
 *
 * Polls once a minute and whenever the tab regains focus. Reading the list is also what
 * makes the server raise due contract reminders (there is no scheduler in the stack), so
 * the poll is not only a refresh — it is what keeps a deposit due tomorrow from being
 * missed by someone who never opens the Series page.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Bell, CheckCheck, Loader2 } from "lucide-react";

import {
  NOTIFICATIONS_CHANGED, SEVERITY_STYLE, ago, fetchNotifications, markNotificationsRead,
  type AppNotification,
} from "@/lib/notifications";

const POLL_MS = 60_000;

export default function NotificationBell() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<AppNotification[]>([]);
  const [unread, setUnread] = useState(0);
  const [loading, setLoading] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  // A failed poll keeps the last list — the bell is a courtesy, not a gate.
  const load = useCallback(() => fetchNotifications({ limit: 20 })
    .then((data) => {
      setItems(data.items);
      setUnread(data.unread_count);
    })
    .catch(() => undefined), []);

  useEffect(() => {
    load();
    const timer = setInterval(load, POLL_MS);
    const onFocus = () => load();
    window.addEventListener("focus", onFocus);
    window.addEventListener(NOTIFICATIONS_CHANGED, onFocus);
    return () => {
      clearInterval(timer);
      window.removeEventListener("focus", onFocus);
      window.removeEventListener(NOTIFICATIONS_CHANGED, onFocus);
    };
  }, [load]);

  // Close on an outside click or Escape.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next) {
      setLoading(true);
      await load();
      setLoading(false);
    }
  };

  const openItem = async (n: AppNotification) => {
    setOpen(false);
    if (!n.read) {
      setItems((prev) => prev.map((x) => (x.id === n.id ? { ...x, read: true } : x)));
      setUnread((u) => Math.max(0, u - 1));
      markNotificationsRead([n.id]).catch(() => undefined);
    }
    if (n.link) router.push(n.link);
  };

  const readAll = async () => {
    setItems((prev) => prev.map((x) => ({ ...x, read: true })));
    setUnread(0);
    await markNotificationsRead().catch(() => undefined);
  };

  return (
    <div className="relative" ref={boxRef}>
      <button
        onClick={toggle}
        aria-label={unread ? `${unread} unread notifications` : "Notifications"}
        className="relative p-2 rounded-xl text-slate-500 hover:bg-slate-100 hover:text-slate-700 transition-colors"
      >
        <Bell className="w-4.5 h-4.5" />
        {unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-4 h-4 px-1 rounded-full bg-red-500 border-2 border-white text-[9px] font-bold text-white grid place-items-center leading-none">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-[380px] max-w-[calc(100vw-24px)] bg-white rounded-xl border border-gray-100 shadow-xl z-50 overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-2.5 border-b border-gray-100">
            <p className="text-xs font-bold text-gray-800">Notifications</p>
            {unread > 0 && (
              <span className="text-[10px] font-semibold text-red-600 bg-red-50 px-1.5 py-0.5 rounded-full">
                {unread} new
              </span>
            )}
            {loading && <Loader2 className="w-3 h-3 animate-spin text-gray-300" />}
            {unread > 0 && (
              <button
                onClick={readAll}
                className="ml-auto flex items-center gap-1 text-[11px] font-semibold text-[#1e3a5f] hover:bg-gray-50 px-2 py-1 rounded-lg"
              >
                <CheckCheck className="w-3.5 h-3.5" /> Mark all read
              </button>
            )}
          </div>

          <div className="max-h-[420px] overflow-y-auto">
            {items.length === 0 ? (
              <div className="px-4 py-10 text-center">
                <Bell className="w-6 h-6 text-gray-200 mx-auto mb-2" />
                <p className="text-xs text-gray-400">You&apos;re all caught up.</p>
                <p className="text-[10px] text-gray-300 mt-1">
                  Contract deadlines and payments due within a week appear here.
                </p>
              </div>
            ) : items.map((n) => (
              <button
                key={n.id}
                onClick={() => openItem(n)}
                className={`w-full text-left flex gap-2.5 px-4 py-2.5 border-b border-gray-50 hover:bg-slate-50 transition-colors ${
                  n.read ? "" : "bg-blue-50/30"
                }`}
              >
                <span className={`mt-1.5 w-2 h-2 rounded-full shrink-0 ${
                  n.read ? "bg-gray-200" : (SEVERITY_STYLE[n.severity] ?? SEVERITY_STYLE.info).dot
                }`} />
                <span className="min-w-0 flex-1">
                  <span className={`block text-[12px] leading-snug ${n.read ? "text-gray-600" : "text-gray-900 font-semibold"}`}>
                    {n.title}
                  </span>
                  {n.body && (
                    <span className="block text-[11px] text-gray-500 mt-0.5 line-clamp-2">{n.body}</span>
                  )}
                  <span className="block text-[10px] text-gray-400 mt-0.5">{ago(n.created_at)}</span>
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
