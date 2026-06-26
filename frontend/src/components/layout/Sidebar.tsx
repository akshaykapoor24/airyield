"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  FileText, Ticket, BarChart2, FolderOpen,
  Settings, ChevronLeft, ChevronDown,
  Plane, Building2, MapPin, Route, Tag, DollarSign,
  Calculator, Upload, ClipboardCheck, CheckSquare,
  AlertTriangle, Edit3, Users, Shield, GitMerge,
  BookOpen, History, Sliders, LayoutGrid, Plus, Contact,
} from "lucide-react";
import { loadDashboards, type CustomDashboard } from "@/lib/customDashboards";
import { cn } from "@/lib/utils";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { toggleSidebar } from "@/store/slices/uiSlice";
import { getUser } from "@/lib/auth";
import { canManageTenantUsers, canSubmitMasterRequest, isPlatformAdmin } from "@/lib/rbac";

type NavItem = {
  label: string;
  href?: string;
  icon: any;
  children?: { label: string; href: string; icon: any }[];
};

const TENANT_NAV: NavItem[] = [
  // { label: "Dashboard", href: "/", icon: LayoutDashboard },
  {
    label: "Dashboards", icon: BarChart2,
    children: [
      { label: "Income Summary", href: "/income-summary", icon: DollarSign },
      { label: "Pending Actions", href: "/pending-actions", icon: ClipboardCheck },
      { label: "Supplier Comparison", href: "/supplier-comparison", icon: GitMerge },
    ],
  },

  {
    label: "Deals", icon: FileText,
    children: [
      { label: "Deal Repository", href: "/deals", icon: FolderOpen },
      { label: "Upload Deal", href: "/deals/upload", icon: Upload },
      { label: "Create Deal", href: "/deals/new", icon: Edit3 },
      // { label: "Review Deals", href: "/deals/review", icon: ClipboardCheck },
      { label: "Approvals", href: "/deals/approvals", icon: CheckSquare },
    ],
  },

  {
    label: "Tickets", icon: Ticket,
    children: [
      { label: "Upload Tickets", href: "/tickets/upload", icon: Upload },
      // { label: "Validation", href: "/tickets/validation", icon: ClipboardCheck },
      { label: "Ticket Repository", href: "/tickets", icon: BookOpen },
      { label: "Income Summary", href: "/tickets/income-summary", icon: DollarSign },
    ],
  },
  { label: "My Customers", href: "/customers", icon: Contact },
  // {
  //   label: "Calculations", icon: Calculator,
  //   children: [
  //     { label: "Run Calculation", href: "/calculations/run", icon: Sliders },
  //     { label: "Output Summary", href: "/calculations/output", icon: BarChart2 },
  //     { label: "Exceptions", href: "/calculations/exceptions", icon: AlertTriangle },
  //     { label: "Manual Overrides", href: "/calculations/overrides", icon: Edit3 },
  //     { label: "Override Approval", href: "/calculations/override-approval", icon: CheckSquare },
  //   ],
  // },
  {
    label: "Masters", icon: Settings,
    children: [
      { label: "Suppliers", href: "/masters/suppliers", icon: Building2 },
      { label: "Airlines", href: "/masters/airlines", icon: Plane },
      { label: "Airports", href: "/masters/airports", icon: MapPin },
      // { label: "Routes", href: "/masters/routes", icon: Route },
      { label: "Classes / RBD", href: "/masters/classes", icon: Tag },
      { label: "Income Heads", href: "/masters/income-heads", icon: DollarSign },
      { label: "Calculation Rules", href: "/masters/calculation-rules", icon: Calculator },
    ],
  },
  {
    label: "Reports", icon: BarChart2,
    children: [
      { label: "Airline-wise", href: "/reports", icon: Plane },
      { label: "Supplier-wise", href: "/reports/supplier", icon: Building2 },
      { label: "Route / Class", href: "/reports/route-class", icon: Route },
      { label: "Period-wise", href: "/reports/period", icon: History },
      { label: "Adjustment", href: "/reports/adjustment", icon: Edit3 },
      { label: "Audit Trail", href: "/reports/audit-trail", icon: BookOpen },
    ],
  },
  { label: "Income Register", href: "/income", icon: DollarSign },
  { label: "Documents", href: "/documents", icon: FolderOpen },
  {
    label: "Admin", icon: Shield,
    children: [
      { label: "User Management", href: "/admin/users", icon: Users },
      { label: "Approval Workflow", href: "/admin/approval-workflow", icon: GitMerge },
      { label: "Roles & Permissions", href: "/admin/roles", icon: Shield },
      { label: "Configuration", href: "/admin/configuration", icon: Settings },
    ],
  },
];

const PLATFORM_NAV: NavItem[] = [
  {
    label: "Master Governance", icon: Settings,
    children: [
      { label: "Suppliers", href: "/masters/suppliers", icon: Building2 },
      { label: "Airlines", href: "/masters/airlines", icon: Plane },
      { label: "Airports", href: "/masters/airports", icon: MapPin },
      // { label: "Routes", href: "/masters/routes", icon: Route },
      { label: "Classes / RBD", href: "/masters/classes", icon: Tag },
      { label: "Income Heads", href: "/masters/income-heads", icon: DollarSign },
      { label: "Calculation Rules", href: "/masters/calculation-rules", icon: Calculator },
    ],
  },
  {
    label: "Administration", icon: Shield,
    children: [
      { label: "Configuration", href: "/admin/configuration", icon: Settings },
      { label: "Approval Inbox", href: "/admin/approval-matrix", icon: GitMerge },
    ],
  },
];

export default function Sidebar() {
  const pathname = usePathname();
  const dispatch = useAppDispatch();
  const open = useAppSelector((s) => s.ui.sidebarOpen);
  const role = getUser()?.role ?? "";
  const platform = isPlatformAdmin(role);
  const navItems = platform ? PLATFORM_NAV : TENANT_NAV;

  const [customDashboards, setCustomDashboards] = useState<CustomDashboard[]>([]);

  useEffect(() => {
    const refresh = () => setCustomDashboards(loadDashboards());
    refresh();
    window.addEventListener("storage", refresh);
    return () => window.removeEventListener("storage", refresh);
  }, [pathname]);

  const isActive = (href: string) =>
    href === "/" ? pathname === "/"
    // "/tickets" (Ticket Repository) matches the list + statement detail pages,
    // but NOT its sibling sub-tabs which have their own entries.
    : href === "/tickets"
      ? pathname === "/tickets" ||
        (pathname.startsWith("/tickets/") &&
          !pathname.startsWith("/tickets/income-summary") &&
          !pathname.startsWith("/tickets/upload"))
    : pathname === href || pathname.startsWith(href + "/");

  const isOnCustomDashboard = pathname.startsWith("/dashboard/");

  const hasActiveChild = (item: NavItem) => {
    if (item.label === "Dashboards" && isOnCustomDashboard) return true;
    return item.children?.some((c) => isActive(c.href)) ?? false;
  };

  const getExpandedFromPathname = () =>
    navItems
      .filter((n) => n.children && (
        n.children.some((c) => isActive(c.href)) ||
        (n.label === "Dashboards" && isOnCustomDashboard)
      ))
      .map((n) => n.label);

  const [expanded, setExpanded] = useState<string[]>(getExpandedFromPathname);

  useEffect(() => {
    setExpanded(getExpandedFromPathname());
  }, [pathname, platform]);

  const toggle = (label: string) =>
    setExpanded((prev) =>
      prev.includes(label) ? prev.filter((l) => l !== label) : [...prev, label]
    );

  return (
    <aside
      className={cn(
        "flex flex-col shrink-0 h-screen sticky top-0 overflow-y-auto transition-all duration-300 text-white",
        open ? "w-60" : "w-[58px]"
      )}
      style={{
        background: platform
          ? "linear-gradient(180deg, #2b1349 0%, #3d1a68 45%, #2b1349 100%)"
          : "linear-gradient(180deg, #0f2540 0%, #122d4e 40%, #0f2540 100%)",
        scrollbarWidth: "none",
      }}
    >
      {/* Logo */}
      <div className={cn(
        "flex items-center h-16 border-b border-white/10 shrink-0 px-3",
        open ? "justify-between" : "justify-center"
      )}>
        {open && (
          <div className="flex items-center gap-2.5 overflow-hidden">
            <div className={cn(
              "rounded-xl p-1.5 shrink-0 shadow-lg",
              platform ? "bg-fuchsia-500 shadow-fuchsia-500/40" : "bg-sky-500 shadow-sky-500/40",
            )}>
              <Plane className="w-4 h-4 text-white" />
            </div>
            <div>
              <span className="text-white font-bold text-base tracking-tight leading-none">AirYield</span>
              <p className={cn(
                "text-[10px] leading-none mt-0.5",
                platform ? "text-fuchsia-300/70" : "text-sky-400/70",
              )}>
                {platform ? "Platform Console" : "Revenue Intelligence"}
              </p>
            </div>
          </div>
        )}
        <button
          onClick={() => dispatch(toggleSidebar())}
          className={cn(
            "p-1.5 rounded-lg text-blue-300/60 hover:text-white hover:bg-white/10 transition-colors shrink-0",
            !open && "mx-auto"
          )}
        >
          <ChevronLeft className={cn("w-4 h-4 transition-transform duration-300", !open && "rotate-180")} />
        </button>
      </div>

      {/* Nav */}
      <nav className="flex-1 py-4 px-2.5 space-y-0.5">
        {navItems.filter((item) => {
          if (item.label === "Masters") return canSubmitMasterRequest(role);
          if (item.label === "Admin") return canManageTenantUsers(role);
          return true;
        }).map((item) => {
          if (!item.children) {
            const active = isActive(item.href!);
            return (
              <Link
                key={item.label}
                href={item.href!}
                title={!open ? item.label : undefined}
                className={cn(
                  "flex items-center gap-3 px-2.5 py-2 rounded-xl text-sm font-medium transition-all duration-150",
                  active
                    ? "text-white shadow-md"
                    : "text-blue-100/60 hover:bg-white/10 hover:text-white"
                )}

                style={active ? { background: "linear-gradient(135deg, #0ea5e9 0%, #2563eb 100%)", boxShadow: "0 4px 12px rgba(14,165,233,0.35)" } : {}}
              >
                <item.icon className={cn("w-4 h-4 shrink-0", active ? "text-white" : "text-blue-200/60")} />
                {open && <span className="truncate">{item.label}</span>}
                {active && open && <span className="ml-auto w-1.5 h-1.5 rounded-full bg-white/60 shrink-0" />}
              </Link>
            );
          }

          const isExpanded = expanded.includes(item.label);
          const childActive = hasActiveChild(item);

          return (
            <div key={item.label}>
              <button
                onClick={() => open && toggle(item.label)}
                title={!open ? item.label : undefined}
                className={cn(
                  "w-full flex items-center gap-3 px-2.5 py-2 rounded-xl text-sm font-medium transition-all duration-150",
                  childActive
                    ? "text-sky-300 bg-white/8"
                    : "text-blue-100/60 hover:bg-white/10 hover:text-white"
                )}
              >
                <item.icon className={cn("w-4 h-4 shrink-0", childActive ? "text-sky-300" : "text-blue-200/60")} />
                {open && (
                  <>
                    <span className="flex-1 text-left truncate">{item.label}</span>
                    <span className={cn("transition-transform duration-200", isExpanded ? "rotate-0" : "-rotate-90")}>
                      <ChevronDown className="w-3.5 h-3.5 opacity-60" />
                    </span>
                  </>
                )}
                {!open && childActive && (
                  <span className="absolute left-1 w-1 h-6 bg-blue-500 rounded-r-full" />
                )}
              </button>

              {open && isExpanded && (
                <div className="mt-0.5 ml-3 pl-3 border-l border-white/10 space-y-0.5 pb-1">
                  {item.children.map((child) => {
                    const active = isActive(child.href);
                    return (
                      <Link
                        key={child.href}
                        href={child.href}
                        className={cn(
                          "flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all duration-150",
                          active
                            ? "bg-sky-500/20 text-sky-200"
                            : "text-blue-200/50 hover:bg-white/8 hover:text-white"
                        )}
                      >
                        <child.icon className={cn("w-3.5 h-3.5 shrink-0", active ? "text-sky-300" : "text-blue-200/50")} />
                        <span className="truncate">{child.label}</span>
                        {active && <span className="ml-auto w-1.5 h-1.5 rounded-full bg-sky-400 shrink-0" />}
                      </Link>
                    );
                  })}

                  {/* Custom dashboards (Dashboards group only) */}
                  {item.label === "Dashboards" && (
                    <>
                      {customDashboards.length > 0 && (
                        <div className="pt-1.5 pb-0.5">
                          <p className="text-[9px] uppercase font-bold text-blue-200/30 tracking-wider px-2.5 mb-1">Custom</p>
                          {customDashboards.map((cd) => {
                            const href = `/dashboard/${cd.id}`;
                            const active = isActive(href);
                            return (
                              <Link
                                key={cd.id}
                                href={href}
                                className={cn(
                                  "flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all duration-150",
                                  active
                                    ? "bg-sky-500/20 text-sky-200"
                                    : "text-blue-200/50 hover:bg-white/8 hover:text-white"
                                )}
                              >
                                <LayoutGrid className={cn("w-3.5 h-3.5 shrink-0", active ? "text-sky-300" : "text-blue-200/50")} />
                                <span className="truncate">{cd.name}</span>
                                {active && <span className="ml-auto w-1.5 h-1.5 rounded-full bg-sky-400 shrink-0" />}
                              </Link>
                            );
                          })}
                        </div>
                      )}
                      <Link
                        href="/dashboard/new"
                        className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-[10px] font-medium text-blue-300/50 hover:text-blue-200 hover:bg-white/8 transition-all duration-150 mt-0.5 border border-dashed border-white/10 hover:border-white/20"
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

      {/* Footer */}
      {open && (
        <div className="px-3 py-3 border-t border-white/10 shrink-0">
          <p className="text-[10px] text-blue-300/40 text-center">AirYield v1.0 · © 2025</p>
        </div>
      )}
    </aside>
  );
}
