"use client";

import { useAuth } from "@/hooks/useAuth";
import { useRouter } from "next/navigation";
import { LogOut, Bell, Search, ChevronDown } from "lucide-react";
import { useState } from "react";
import { isPlatformAdmin } from "@/lib/rbac";

export default function Header() {
  const { user, logout } = useAuth();
  const router = useRouter();
  const [showDropdown, setShowDropdown] = useState(false);
  const platform = isPlatformAdmin(user?.role);

  const handleLogout = async () => {
    await logout();
    router.push("/login");
  };

  const initials = user?.full_name
    ?.split(" ")
    .map((n: string) => n[0])
    .join("")
    .toUpperCase()
    .slice(0, 2) ?? "U";

  return (
    <header className="h-16 flex items-center justify-between px-6 shrink-0 sticky top-0 z-30" style={{
      background: platform
        ? "linear-gradient(135deg, #3d1a68 0%, #5b2596 50%, #4b1f7f 100%)"
        : "linear-gradient(135deg, #1e3a5f 0%, #1e4d8c 50%, #1a3f7a 100%)",
      boxShadow: platform ? "0 2px 12px rgba(61,26,104,0.45)" : "0 2px 12px rgba(30,58,95,0.4)",
    }}>

      {/* Left — Search */}
      <div className="relative w-72">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-blue-200" />
        <input
          type="text"
          placeholder={platform ? "Search master requests, entities..." : "Search deals, tickets, reports..."}
          className="w-full pl-9 pr-4 py-2 text-sm bg-white/15 border border-white/20 rounded-xl text-white placeholder:text-blue-200 focus:outline-none focus:ring-2 focus:ring-white/40 focus:bg-white/20 transition-colors"
        />
      </div>

      {/* Right */}
      <div className="flex items-center gap-2">

        {/* Notification Bell */}
        <button className="relative p-2 rounded-xl text-blue-100 hover:bg-white/15 transition-colors">
          <Bell className="w-4.5 h-4.5" />
          <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-red-400 rounded-full border-2 border-blue-600" />
        </button>

        {/* Divider */}
        <div className="w-px h-6 bg-white/20 mx-1" />

        {/* User Menu */}
        <div className="relative">
          <button
            onClick={() => setShowDropdown((p) => !p)}
            className="flex items-center gap-2.5 px-2 py-1.5 rounded-xl hover:bg-white/15 transition-colors"
          >
            {/* Avatar */}
            <div className="w-8 h-8 rounded-xl flex items-center justify-center text-white text-xs font-bold shadow-md" style={{ background: "linear-gradient(135deg, #38bdf8 0%, #818cf8 100%)" }}>
              {initials}
            </div>
            <div className="text-left hidden sm:block">
              <p className="text-sm font-semibold text-white leading-none">{user?.full_name ?? "User"}</p>
              <p className="text-xs text-blue-200 mt-0.5 capitalize leading-none">{user?.role ?? "Agent"}</p>
            </div>
            <ChevronDown className="w-3.5 h-3.5 text-blue-200" />
          </button>

          {showDropdown && (
            <>
              {/* Backdrop */}
              <div className="fixed inset-0 z-10" onClick={() => setShowDropdown(false)} />
              {/* Dropdown */}
              <div className="absolute right-0 top-full mt-2 w-48 bg-white rounded-2xl border border-gray-100 shadow-xl shadow-gray-200/60 z-20 overflow-hidden">
                <div className="px-4 py-3 border-b border-gray-100">
                  <p className="text-sm font-semibold text-gray-900">{user?.full_name}</p>
                  <p className="text-xs text-gray-400 mt-0.5">{user?.email ?? "admin@airyield.com"}</p>
                </div>
                <div className="py-1.5">
                  <button className="w-full text-left px-4 py-2 text-sm text-gray-600 hover:bg-gray-50 transition-colors">
                    Profile Settings
                  </button>
                  <button className="w-full text-left px-4 py-2 text-sm text-gray-600 hover:bg-gray-50 transition-colors">
                    Change Password
                  </button>
                </div>
                <div className="border-t border-gray-100 py-1.5">
                  <button
                    onClick={handleLogout}
                    className="w-full text-left px-4 py-2 text-sm text-red-500 hover:bg-red-50 transition-colors flex items-center gap-2"
                  >
                    <LogOut className="w-3.5 h-3.5" />
                    Sign Out
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
