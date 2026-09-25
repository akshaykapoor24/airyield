"use client";

import { useAuth } from "@/hooks/useAuth";
import { Search } from "lucide-react";
import { isPlatformAdmin } from "@/lib/rbac";
import NotificationBell from "@/components/layout/NotificationBell";

export default function Header() {
  const { user } = useAuth();
  const platform = isPlatformAdmin(user?.role);

  return (
    <header
      className="h-16 flex items-center justify-between px-6 shrink-0 sticky top-0 z-30 bg-white border-b border-[#e6ebf2]"
      style={{ boxShadow: "0 1px 3px rgba(15,37,64,0.06)" }}
    >
      {/* Left — Search */}
      <div className="relative w-72">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
        <input
          type="text"
          placeholder={platform ? "Search master requests, entities..." : "Search deals, tickets, reports..."}
          className="w-full pl-9 pr-4 py-2 text-sm bg-[#f1f5f9] border border-[#e2e8f0] rounded-xl text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-300 focus:bg-white transition-colors"
        />
      </div>

      {/* Right — Notifications (the account menu now lives in the sidebar footer) */}
      <div className="flex items-center gap-2">
        {/* Platform admins have no workspace, so nothing is addressed to them. */}
        {!platform && <NotificationBell />}
      </div>
    </header>
  );
}
