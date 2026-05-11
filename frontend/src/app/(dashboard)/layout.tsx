"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import Sidebar from "@/components/layout/Sidebar";
import Header from "@/components/layout/Header";
import { getUser, isAuthenticated } from "@/lib/auth";
import { isPlatformAdmin } from "@/lib/rbac";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login");
    } else {
      const role = getUser()?.role;
      const platform = isPlatformAdmin(role);
      if (platform && !pathname.startsWith("/masters") && !pathname.startsWith("/admin")) {
        router.replace("/masters/airports");
        return;
      }
      setReady(true);
    }
  }, [router, pathname]);

  if (!ready) return null;

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex flex-col flex-1 overflow-hidden">
        <Header />
        <main className="flex-1 overflow-y-auto p-6 bg-gray-50">
          {children}
        </main>
      </div>
    </div>
  );
}
