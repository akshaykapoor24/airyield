"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  BarChart2, FileText, Ticket, FolderOpen, FolderOutput, Settings,
  ChevronLeft, ChevronDown, Send, UserCircle, KeyRound, LogOut,
  Plane, Building, Building2, MapPin, Route, Tag, DollarSign,
  Calculator, Upload, ClipboardCheck, CheckSquare,
  Edit3, Users, Shield, GitMerge, Search,
  BookOpen, History, LayoutGrid, Plus, Contact, Percent, FilePlus, Layers,
} from "lucide-react";
import { loadDashboards, type CustomDashboard } from "@/lib/customDashboards";
import { cn } from "@/lib/utils";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { toggleSidebar } from "@/store/slices/uiSlice";
import { logout as logoutThunk } from "@/store/slices/authSlice";
import { getUser } from "@/lib/auth";
import { canManageTenantUsers, canSubmitMasterRequest, isPlatformAdmin } from "@/lib/rbac";
import ChangePasswordModal from "@/components/layout/ChangePasswordModal";

type NavChild = { label: string; href: string; icon: any; badge?: number };
type NavItem = {
  id: string;
  label: string;
  href?: string;
  icon?: any;
  divider?: boolean;
  children?: NavChild[];
};

const TENANT_NAV: NavItem[] = [
  // ────────────── New information architecture (top) ──────────────
  {
    id: "dashboard", label: "Dashboard", icon: BarChart2,
    children: [
      { label: "Overview", href: "/dashboard", icon: LayoutGrid },
      { label: "Pending Actions", href: "/pending-actions", icon: ClipboardCheck },
      { label: "Supplier Comparison", href: "/supplier-comparison", icon: GitMerge },
    ],
  },

  {
    id: "vendors", label: "Vendors data", icon: FolderOpen,
    children: [
      { label: "Incoming deals", href: "/deals", icon: FolderOpen },
      // TODO: wire badge to real count
      { label: "Statements", href: "/vendors/statements", icon: FileText },
      { label: "Series/SIT/MICE", href: "/vendors/series-sit-mice", icon: Layers },
      { label: "Ticket Search", href: "/ticket-details", icon: Search },
      { label: "Reconciliation", href: "/tickets/bsp-reconciliation", icon: GitMerge },
      { label: "Commission income", href: "/vendors/commission-income", icon: DollarSign },
    ],
  },

  {
    id: "customers", label: "Customer data", icon: Contact,
    children: [
      // Customer directory = the sub-agencies we onboard and float deals to (NOT our own
      // customer list). One page with in-page Onboarding / Overview tabs.
      { label: "Customer directory", href: "/customers/directory", icon: Contact },
      { label: "Floated deals", href: "/deals?direction=outbound", icon: FolderOutput },
      { label: "Statements", href: "/customers/statements", icon: FileText },
      { label: "Reconciliation", href: "/customers/reconciliation", icon: GitMerge },
      // { label: "Billing and invoices", href: "/billing/agency", icon: DollarSign },
    ],
  },

  {
    id: "tickets", label: "Internal Statement", icon: Ticket,
    children: [
      { label: "Internal Statement", href: "/tickets", icon: BookOpen },
      { label: "Upload Statement", href: "/tickets/upload", icon: Upload },
      { label: "Create Tickets", href: "/tickets/create", icon: FilePlus },
      { label: "Income Statement", href: "/tickets/income-summary", icon: DollarSign },
    ],
  },

  {
    id: "billing", label: "Billing", icon: Contact,
    children: [
      { label: "Customer Billing", href: "/customers", icon: Contact },
      { label: "Agency Billing", href: "/billing/agency", icon: Building2 },
      { label: "Corporate Billing", href: "/corporates", icon: Building },
    ],
  },

  {
    id: "agency-profile", label: "User master", icon: Users,
    children: [
      // Agency Onboarding + Overview moved into "Customer data" (they ARE the customer directory).
      { label: "IATA Commission", href: "/user-master/iata-commission", icon: Percent },
    ],
  },

  {
    id: "reports", label: "Reports", icon: BarChart2,
    children: [
      { label: "Airline-wise", href: "/reports", icon: Plane },
      { label: "Supplier-wise", href: "/reports/supplier", icon: Building2 },
      { label: "Route / Class", href: "/reports/route-class", icon: Route },
      { label: "Period-wise", href: "/reports/period", icon: History },
      { label: "Adjustment", href: "/reports/adjustment", icon: Edit3 },
      { label: "Audit Trail", href: "/reports/audit-trail", icon: BookOpen },
    ],
  },

  {
    // "update", not "master": a tenant user submits changes here and sees their
    // own submissions. The master data itself belongs to Master Governance,
    // which only a platform admin can reach. Income heads and calculation rules
    // are omitted until they hold real data.
    id: "system-master", label: "System master update", icon: Settings,
    children: [
      { label: "Suppliers", href: "/masters/suppliers", icon: Building2 },
      { label: "Airlines", href: "/masters/airlines", icon: Plane },
      { label: "Airports", href: "/masters/airports", icon: MapPin },
      { label: "Classes / RBD", href: "/masters/classes", icon: Tag },
    ],
  },

  {
    id: "workspace", label: "Workspace", icon: FolderOpen,
    children: [
      { label: "Uploaded documents", href: "/documents", icon: FolderOpen },
      // TODO: wire badge to real count
      { label: "Approvals", href: "/deals/approvals", icon: CheckSquare, badge: 4 },
    ],
  },

  {
    id: "admin", label: "Admin", icon: Shield,
    children: [
      { label: "User management", href: "/admin/users", icon: Users },
      { label: "Approval workflow", href: "/admin/approval-workflow", icon: GitMerge },
      { label: "Roles and permissions", href: "/admin/roles", icon: Shield },
      { label: "Configuration", href: "/admin/configuration", icon: Settings },
    ],
  },

];

const PLATFORM_NAV: NavItem[] = [
  {
    id: "master-governance", label: "Master Governance", icon: Settings,
    children: [
      { label: "Suppliers", href: "/masters/suppliers", icon: Building2 },
      { label: "Airlines", href: "/masters/airlines", icon: Plane },
      { label: "Airports", href: "/masters/airports", icon: MapPin },
      { label: "Classes / RBD", href: "/masters/classes", icon: Tag },
      { label: "Income Heads", href: "/masters/income-heads", icon: DollarSign },
      { label: "Calculation Rules", href: "/masters/calculation-rules", icon: Calculator },
    ],
  },
  {
    id: "administration", label: "Administration", icon: Shield,
    children: [
      { label: "Configuration", href: "/admin/configuration", icon: Settings },
      { label: "Approval Inbox", href: "/admin/approval-matrix", icon: GitMerge },
    ],
  },
];

export default function Sidebar() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const dispatch = useAppDispatch();
  const open = useAppSelector((s) => s.ui.sidebarOpen);
  const user = getUser();
  const role = user?.role ?? "";
  const platform = isPlatformAdmin(role);
  const navItems = platform ? PLATFORM_NAV : TENANT_NAV;

  // Light-theme accent palette — blue for tenants, purple for the platform console.
  const theme = platform
    ? { accent: "#9333ea", accentDark: "#7c3aed", softBg: "#faf5ff", border: "#e9d5ff" }
    : { accent: "#2563eb", accentDark: "#1d4ed8", softBg: "#eff6ff", border: "#bfdbfe" };

  // Footer account menu (moved down from the top header)
  const displayName = user?.full_name || "User";
  const email = user?.email || "";
  const initials =
    displayName.split(" ").filter(Boolean).map((n) => n[0]).join("").toUpperCase().slice(0, 2) || "U";
  const router = useRouter();
  const [showProfileMenu, setShowProfileMenu] = useState(false);
  const [showChangePw, setShowChangePw] = useState(false);
  const handleLogout = async () => {
    setShowProfileMenu(false);
    await dispatch(logoutThunk());
    router.push("/login");
  };

  const [customDashboards, setCustomDashboards] = useState<CustomDashboard[]>([]);

  useEffect(() => {
    const refresh = () => setCustomDashboards(loadDashboards());
    refresh();
    window.addEventListener("storage", refresh);
    return () => window.removeEventListener("storage", refresh);
  }, [pathname]);

  const isActive = (href: string) =>
    // Incoming / Outgoing deal repos share the /deals page and differ only by the
    // ?direction query, so match on pathname + the direction param.
    href === "/deals"
      ? pathname === "/deals" && searchParams.get("direction") !== "outbound"
    : href === "/deals?direction=outbound"
      ? pathname === "/deals" && searchParams.get("direction") === "outbound"
    : href === "/" ? pathname === "/"
    // "/tickets" (Ticket Repository) matches the list + statement detail pages,
    // but NOT its sibling sub-tabs which have their own entries.
    : href === "/tickets"
      ? pathname === "/tickets" ||
        (pathname.startsWith("/tickets/") &&
          !pathname.startsWith("/tickets/income-summary") &&
          !pathname.startsWith("/tickets/upload") &&
          !pathname.startsWith("/tickets/create") &&
          !pathname.startsWith("/tickets/bsp") &&
          !pathname.startsWith("/tickets/adjustments"))
    : pathname === href || pathname.startsWith(href + "/");

  const isOnCustomDashboard = pathname.startsWith("/dashboard/");

  const hasActiveChild = (item: NavItem) => {
    if (item.id === "dashboard" && isOnCustomDashboard) return true;
    return item.children?.some((c) => isActive(c.href)) ?? false;
  };

  const getExpandedFromPathname = () =>
    navItems
      .filter((n) => n.children && (
        n.children.some((c) => isActive(c.href)) ||
        (n.id === "dashboard" && isOnCustomDashboard)
      ))
      .map((n) => n.id);

  const [expanded, setExpanded] = useState<string[]>(getExpandedFromPathname);

  useEffect(() => {
    setExpanded(getExpandedFromPathname());
  }, [pathname, platform]);

  const toggle = (id: string) =>
    setExpanded((prev) =>
      prev.includes(id) ? prev.filter((l) => l !== id) : [...prev, id]
    );

  return (
    <>
    <aside
      className={cn(
        "flex flex-col shrink-0 h-screen sticky top-0 overflow-y-auto transition-all duration-300 bg-white border-r border-[#e6ebf2] text-slate-700",
        open ? "w-60" : "w-[58px]"
      )}
      style={{ scrollbarWidth: "none" }}
    >
      {/* Logo */}
      <div className={cn(
        "flex items-center h-16 border-b border-[#e6ebf2] shrink-0 px-3",
        open ? "justify-between" : "justify-center"
      )}>
        {open && (
          <div className="flex items-center gap-2.5 overflow-hidden">
            <div
              className="rounded-xl p-2 shrink-0"
              style={{
                background: platform
                  ? "linear-gradient(135deg, #a855f7 0%, #7c3aed 100%)"
                  : "linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)",
                boxShadow: platform
                  ? "0 4px 12px rgba(147,51,234,0.30)"
                  : "0 4px 12px rgba(37,99,235,0.30)",
              }}
            >
              <Send className="w-4 h-4 text-white" />
            </div>
            <div className="leading-none">
              <span className="font-bold text-xl tracking-tight leading-none">
                <span className="text-slate-800">Fare</span>
                <span className="text-orange-500">Qube</span>
              </span>
              <p className="text-[10px] leading-none mt-1 text-slate-400 tracking-wide">
                {platform ? "Platform Console" : "Revenue Intelligence"}
              </p>
            </div>
          </div>
        )}
        <button
          onClick={() => dispatch(toggleSidebar())}
          className={cn(
            "p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors shrink-0",
            !open && "mx-auto"
          )}
        >
          <ChevronLeft className={cn("w-4 h-4 transition-transform duration-300", !open && "rotate-180")} />
        </button>
      </div>

      {/* Nav */}
      <nav className="flex-1 py-4 px-2.5 space-y-0.5">
        {navItems.filter((item) => {
          if (item.id === "system-master") return canSubmitMasterRequest(role);
          if (item.id === "admin") return canManageTenantUsers(role);
          return true;
        }).map((item) => {
          // Section divider
          if (item.divider) {
            if (!open) return <div key={item.id} className="my-2 mx-2 border-t border-[#e6ebf2]" />;
            return (
              <div key={item.id} className="flex items-center gap-2 px-2.5 pt-4 pb-1">
                <span className="text-[10px] uppercase font-semibold text-slate-400 tracking-wider">{item.label}</span>
                <span className="flex-1 border-t border-[#e6ebf2]" />
              </div>
            );
          }

          // Standalone link
          if (!item.children) {
            const active = isActive(item.href!);
            return (
              <Link
                key={item.id}
                href={item.href!}
                title={!open ? item.label : undefined}
                className={cn(
                  "flex items-center gap-3 px-2.5 py-2 rounded-xl text-sm font-medium transition-all duration-150",
                  active ? "font-semibold" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                )}
                style={active ? { background: theme.softBg, color: theme.accent } : {}}
              >
                {item.icon && (
                  <item.icon className="w-4 h-4 shrink-0" style={active ? { color: theme.accent } : { color: "#94a3b8" }} />
                )}
                {open && <span className="truncate">{item.label}</span>}
              </Link>
            );
          }

          // Collapsible group
          const isExpanded = expanded.includes(item.id);
          const childActive = hasActiveChild(item);

          return (
            <div key={item.id}>
              <button
                onClick={() => open && toggle(item.id)}
                title={!open ? item.label : undefined}
                className={cn(
                  "relative w-full flex items-center gap-3 px-2.5 py-2 rounded-xl text-sm font-medium transition-all duration-150 border",
                  childActive
                    ? "font-semibold"
                    : "border-transparent text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                )}
                style={childActive ? { background: theme.softBg, color: theme.accentDark, borderColor: theme.border } : {}}
              >
                {item.icon && (
                  <item.icon className="w-4 h-4 shrink-0" style={childActive ? { color: theme.accent } : { color: "#94a3b8" }} />
                )}
                {open && (
                  <>
                    <span className="flex-1 text-left truncate">{item.label}</span>
                    <span className={cn("transition-transform duration-200", isExpanded ? "rotate-0" : "-rotate-90")}>
                      <ChevronDown className="w-3.5 h-3.5 opacity-50" />
                    </span>
                  </>
                )}
                {!open && childActive && (
                  <span className="absolute left-0.5 top-1/2 -translate-y-1/2 w-1 h-6 rounded-r-full" style={{ background: theme.accent }} />
                )}
              </button>

              {open && isExpanded && (
                <div className="mt-0.5 ml-3 pl-3 border-l border-[#e6ebf2] space-y-0.5 pb-1">
                  {item.children.map((child) => {
                    const active = isActive(child.href);
                    return (
                      <Link
                        key={child.href}
                        href={child.href}
                        className={cn(
                          "flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all duration-150",
                          active ? "font-semibold" : "text-slate-500 hover:bg-slate-100 hover:text-slate-900"
                        )}
                        style={active ? { background: theme.softBg, color: theme.accent } : {}}
                      >
                        <child.icon className="w-3.5 h-3.5 shrink-0" style={active ? { color: theme.accent } : { color: "#94a3b8" }} />
                        <span className="truncate">{child.label}</span>
                        {child.badge != null && (
                          <span className="ml-auto shrink-0 min-w-[18px] h-[18px] px-1 inline-flex items-center justify-center rounded-full text-[10px] font-bold bg-orange-100 text-orange-600">
                            {child.badge}
                          </span>
                        )}
                      </Link>
                    );
                  })}

                  {/* Custom dashboards (legacy Dashboard group only) */}
                  {item.id === "dashboard" && (
                    <>
                      {customDashboards.length > 0 && (
                        <div className="pt-1.5 pb-0.5">
                          <p className="text-[9px] uppercase font-bold text-slate-400 tracking-wider px-2.5 mb-1">Custom</p>
                          {customDashboards.map((cd) => {
                            const href = `/dashboard/${cd.id}`;
                            const active = isActive(href);
                            return (
                              <Link
                                key={cd.id}
                                href={href}
                                className={cn(
                                  "flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all duration-150",
                                  active ? "font-semibold" : "text-slate-500 hover:bg-slate-100 hover:text-slate-900"
                                )}
                                style={active ? { background: theme.softBg, color: theme.accent } : {}}
                              >
                                <LayoutGrid className="w-3.5 h-3.5 shrink-0" style={active ? { color: theme.accent } : { color: "#94a3b8" }} />
                                <span className="truncate">{cd.name}</span>
                              </Link>
                            );
                          })}
                        </div>
                      )}
                      <Link
                        href="/dashboard/new"
                        className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-[10px] font-medium text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-all duration-150 mt-0.5 border border-dashed border-[#e6ebf2] hover:border-slate-300"
                      >
                        <Plus className="w-3 h-3 shrink-0" />
                        <span>Create Dashboard</span>
                      </Link>
                    </>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </nav>

      {/* Footer — account menu (moved down from the top header) */}
      <div className="relative border-t border-[#e6ebf2] shrink-0 p-2.5">
        {showProfileMenu && (
          <>
            {/* Backdrop */}
            <div className="fixed inset-0 z-30" onClick={() => setShowProfileMenu(false)} />
            {/* Pop-up menu (opens upward) */}
            <div className="absolute bottom-full mb-2 left-2 right-2 min-w-[13rem] bg-white rounded-2xl border border-[#e6ebf2] shadow-xl shadow-slate-200/60 z-40 overflow-hidden">
              <div className="px-4 py-3 border-b border-[#e6ebf2]">
                <p className="text-sm font-semibold text-slate-900 truncate">{displayName}</p>
                <p className="text-xs text-slate-400 mt-0.5 truncate">{email || "—"}</p>
              </div>
              <div className="py-1.5">
                <Link
                  href="/profile"
                  onClick={() => setShowProfileMenu(false)}
                  className="flex items-center gap-2.5 w-full px-4 py-2 text-sm text-slate-600 hover:bg-slate-50 transition-colors"
                >
                  <UserCircle className="w-4 h-4 text-slate-400 shrink-0" />
                  Ind / Corp profile
                </Link>
                <button
                  type="button"
                  onClick={() => { setShowProfileMenu(false); setShowChangePw(true); }}
                  className="flex items-center gap-2.5 w-full px-4 py-2 text-sm text-slate-600 hover:bg-slate-50 transition-colors"
                >
                  <KeyRound className="w-4 h-4 text-slate-400 shrink-0" />
                  Change Password
                </button>
              </div>
              <div className="border-t border-[#e6ebf2] py-1.5">
                <button
                  type="button"
                  onClick={handleLogout}
                  className="flex items-center gap-2.5 w-full px-4 py-2 text-sm text-red-500 hover:bg-red-50 transition-colors"
                >
                  <LogOut className="w-4 h-4 shrink-0" />
                  Sign Out
                </button>
              </div>
            </div>
          </>
        )}

        <button
          type="button"
          onClick={() => setShowProfileMenu((p) => !p)}
          title={!open ? displayName : undefined}
          className={cn(
            "w-full flex items-center gap-2.5 rounded-xl transition-colors hover:bg-slate-100",
            open ? "px-2 py-2" : "p-1.5 justify-center",
            showProfileMenu && "bg-slate-100"
          )}
        >
          <div
            className="w-8 h-8 rounded-xl flex items-center justify-center text-white text-xs font-bold shadow-sm shrink-0"
            style={{
              background: platform
                ? "linear-gradient(135deg, #c084fc 0%, #9333ea 100%)"
                : "linear-gradient(135deg, #38bdf8 0%, #2563eb 100%)",
            }}
          >
            {initials}
          </div>
          {open && (
            <>
              <div className="flex-1 min-w-0 text-left">
                <p className="text-sm font-semibold text-slate-900 leading-tight truncate">{displayName}</p>
                <p className="text-[11px] text-slate-400 leading-tight truncate">{email || "Ind / Corp profile"}</p>
              </div>
              <ChevronDown className={cn("w-4 h-4 text-slate-400 shrink-0 transition-transform", showProfileMenu && "rotate-180")} />
            </>
          )}
        </button>
      </div>
    </aside>

    {/* Sibling of the <aside>, not a child: the aside is overflow-y-auto, and a
        sibling is immune if it ever grows a transform (which would re-parent a
        fixed-position child). */}
    {showChangePw && <ChangePasswordModal onClose={() => setShowChangePw(false)} />}
    </>
  );
}
