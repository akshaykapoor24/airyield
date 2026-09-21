"use client";

// Guard for everything under /admin.
//
// The sidebar only shows the Admin group to the Super Admin, but hiding a link is not a
// restriction: a team member who typed /admin/roles or /admin/configuration used to get the
// page. The APIs behind these pages already refuse them (the users and approval-workflow
// routers require Super Admin); this stops the pages themselves rendering.
//
// Two roles pass:
//   * the SUPER ADMIN — User management, Approval workflow, Roles, Configuration;
//   * the PLATFORM ADMIN — whose console also lives here (Subscriptions, Configuration,
//     Approval Inbox). Those pages keep their own, narrower checks.
// Everyone else is sent to the dashboard.

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getUser } from "@/lib/auth";
import { canManageTenantUsers, isPlatformAdmin } from "@/lib/rbac";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  // Safe to read in render: the dashboard layout above renders nothing until it has
  // confirmed the session in the browser, so this never runs on the server.
  const role = getUser()?.role;
  const allowed = canManageTenantUsers(role) || isPlatformAdmin(role);

  useEffect(() => {
    if (!allowed) router.replace("/dashboard");
  }, [allowed, router]);

  if (!allowed) return null;
  return <>{children}</>;
}
