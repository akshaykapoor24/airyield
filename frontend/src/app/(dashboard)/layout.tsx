"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { usePathname, useRouter } from "next/navigation";
import Sidebar from "@/components/layout/Sidebar";
import Header from "@/components/layout/Header";
import { getUser, isAuthenticated } from "@/lib/auth";
import { isPlatformAdmin } from "@/lib/rbac";
import { getPlanBlocked, getPlanBlockedServer, subscribePlanGate } from "@/lib/planGate";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { fetchMe } from "@/store/slices/authSlice";
import OnboardingWizard from "@/components/onboarding/OnboardingWizard";
import NoActivePlanGate from "@/components/plan/NoActivePlanGate";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const dispatch = useAppDispatch();
  const [ready, setReady] = useState(false);
  const [onboardingDone, setOnboardingDone] = useState(false);
  const reduxUser = useAppSelector((s) => s.auth.user);
  // Raised by the axios interceptor on a 402 — covers the window between a
  // workspace being suspended and this tab noticing.
  const planBlocked = useSyncExternalStore(subscribePlanGate, getPlanBlocked, getPlanBlockedServer);

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

  // Refresh the cached user once per mount. `ay_user` in localStorage is written
  // at login and never expires, so a session that signed in before subscriptions
  // shipped carries no plan_active at all — and a workspace suspended since
  // login would still look active. /users/me is exempt from the paywall for
  // exactly this reason.
  useEffect(() => {
    if (isAuthenticated()) dispatch(fetchMe());
  }, [dispatch]);

  if (!ready) return null;

  const user = reduxUser ?? getUser();

  // No active plan → the whole dashboard is replaced, not overlaid: nothing
  // behind this mounts, so no page fires a request that would only 402. Returns
  // before the onboarding wizard too — a frozen workspace has nothing to set up.
  // Platform admins own global master data and belong to no customer workspace,
  // so the paywall never applies to them (the backend agrees).
  const frozen =
    !!user && !isPlatformAdmin(user.role) && (user.plan_active === false || planBlocked);
  if (frozen) return <NoActivePlanGate user={user} />;

  // First-login onboarding: block the dashboard with the wizard until finished.
  // CORPORATE workspaces only — entities and airline login IDs are company setup.
  // An individual account is a private single-person workspace with nothing to
  // configure up front, so it goes straight to the dashboard and can still add
  // entities and login IDs later from My Profile.
  // Platform admins and already-onboarded users skip it either way.
  const showOnboarding =
    !onboardingDone &&
    !!user &&
    !isPlatformAdmin(user.role) &&
    user.tenant_type === "corporate" &&
    user.onboarding_complete === false;

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
