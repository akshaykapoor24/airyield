export const APP_ROLES = [
  "platform_admin",
  "super_admin",
  "company_admin",
  "operations_user",
  "finance_user",
  "approver",
  "viewer",
] as const;

export type AppRole = (typeof APP_ROLES)[number];

export function isPlatformAdmin(role?: string | null): boolean {
  return role === "platform_admin";
}

export function canManageTenantUsers(role?: string | null): boolean {
  return role === "super_admin";
}

/** Who manages the workspace itself: its company details, logo, GST scheme, entities and
 *  login IDs / IATA numbers — the Super Admin. Everyone else sees the company details and
 *  the entities granted to them in User management, read-only, and may change only their
 *  own name. Mirrors backend services/entity_access.can_manage_entities, which enforces
 *  it; this only decides what the screens offer. */
export function canManageWorkspace(role?: string | null): boolean {
  return role === "super_admin";
}

export function canAccessTenantWorkspace(role?: string | null): boolean {
  return !!role && role !== "platform_admin";
}

export function canManageGlobalMasters(role?: string | null): boolean {
  return isPlatformAdmin(role);
}

export function canSubmitMasterRequest(role?: string | null): boolean {
  if (!role) return false;
  return role !== "viewer";
}

export function canViewMasterRequests(role?: string | null): boolean {
  return canManageGlobalMasters(role) || canSubmitMasterRequest(role);
}
