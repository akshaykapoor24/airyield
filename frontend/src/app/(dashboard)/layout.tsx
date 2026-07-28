"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import Sidebar from "@/components/layout/Sidebar";
import Header from "@/components/layout/Header";
import { getUser, isAuthenticated } from "@/lib/auth";
import { isPlatformAdmin } from "@/lib/rbac";
import { useAppSelector } from "@/store/hooks";
import OnboardingWizard from "@/components/onboarding/OnboardingWizard";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [ready, setReady] = useState(false);
  const [onboardingDone, setOnboardingDone] = useState(false);
  const reduxUser = useAppSelector((s) => s.auth.user);

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

  // First-login onboarding: block the dashboard with the wizard until finished.
  // Only tenant users created via signup carry onboarding_complete === false;
  // platform admins and already-onboarded users skip it.
  const user = reduxUser ?? getUser();
  const showOnboarding =
    !onboardingDone && !!user && !isPlatformAdmin(user.role) && user.onboarding_complete === false;

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex flex-col flex-1 overflow-hidden">
        <Header />
        <main className="flex-1 overflow-y-auto p-6 bg-gray-50">
          {children}
        </main>
      </div>
      {showOnboarding && <OnboardingWizard onComplete={() => setOnboardingDone(true)} />}
    </div>
  );
}
