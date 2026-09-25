"use client";

/**
 * The contract reminders that are also in the bell, shown above the Series list — the
 * place someone looking at contracts is most able to act on them.
 *
 * Same rows as the bell (category "series"), so dismissing one here clears it there, and
 * the other way round, via the NOTIFICATIONS_CHANGED event.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { BellRing, X } from "lucide-react";

import {
  NOTIFICATIONS_CHANGED, SEVERITY_STYLE, fetchNotifications, markNotificationsRead,
  type AppNotification,
} from "@/lib/notifications";

const SHOWN = 6;

export default function SeriesReminders({ refreshKey = 0 }: { refreshKey?: number }) {
  const [items, setItems] = useState<AppNotification[]>([]);
  const [total, setTotal] = useState(0);

  // A failed read shows nothing; the action tiles below still show what is due.
  const load = useCallback(() => fetchNotifications({ category: "series", unread_only: true, limit: 30 })
    .then((data) => {
      setItems(data.items);
      setTotal(data.unread_count);
    })
    .catch(() => undefined), []);

  useEffect(() => { load(); }, [load, refreshKey]);
  useEffect(() => {
    window.addEventListener(NOTIFICATIONS_CHANGED, load);
    return () => window.removeEventListener(NOTIFICATIONS_CHANGED, load);
  }, [load]);

  if (!items.length) return null;

  const dismiss = async (ids: number[]) => {
    setItems((prev) => prev.filter((n) => !ids.includes(n.id)));
    setTotal((t) => Math.max(0, t - ids.length));
    await markNotificationsRead(ids).catch(() => undefined);
  };

  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-gray-100">
        <BellRing className="w-3.5 h-3.5 text-[#1e3a5f]" />
        <p className="text-xs font-bold text-gray-800 uppercase tracking-wide">Reminders</p>
        <span className="text-[10px] font-semibold text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded-full">{total}</span>
        <button
          onClick={() => dismiss(items.map((n) => n.id))}
          className="ml-auto text-[11px] font-semibold text-gray-500 hover:text-gray-700 hover:bg-gray-50 px-2 py-1 rounded-lg"
        >
          Dismiss all
        </button>
      </div>
      <ul className="divide-y divide-gray-50">
        {items.slice(0, SHOWN).map((n) => {
          const tone = SEVERITY_STYLE[n.severity] ?? SEVERITY_STYLE.info;
          return (
            <li key={n.id} className="flex items-start gap-2.5 px-4 py-2 hover:bg-slate-50/60">
              <span className={`mt-1.5 w-2 h-2 rounded-full shrink-0 ${tone.dot}`} />
              <Link
                href={n.link ?? "#"}
                onClick={() => markNotificationsRead([n.id]).catch(() => undefined)}
                className="min-w-0 flex-1"
              >
                <span className="block text-[12px] font-semibold text-gray-800 leading-snug">{n.title}</span>
                {n.body && <span className="block text-[11px] text-gray-500 line-clamp-1">{n.body}</span>}
              </Link>
              <button onClick={() => dismiss([n.id])} title="Dismiss" className="p-1 hover:bg-gray-100 rounded">
                <X className="w-3 h-3 text-gray-400" />
              </button>
            </li>
          );
        })}
      </ul>
      {items.length > SHOWN && (
        <p className="px-4 py-1.5 text-[10px] text-gray-400 border-t border-gray-50">
          {items.length - SHOWN} more in the notification bell.
        </p>
      )}
    </div>
  );
}
