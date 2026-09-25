"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { LucideIcon } from "lucide-react";
import { PlaneTakeoff, Receipt, ShieldAlert } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * The shared frame of the three revenue boards — Total Revenue, Sales vs Flown and Risk
 * analysis — so they read as one product rather than three pages that happen to sit
 * next to each other in the sidebar.
 *
 * Presentation only. Nothing here knows what a sale is; every figure still comes from
 * the page that renders it.
 */

// ── Tabs across the three boards ────────────────────────────────────────────

const BOARDS: { href: string; label: string; icon: LucideIcon; blurb: string }[] = [
  { href: "/dashboard/revenue", label: "Total Revenue", icon: Receipt, blurb: "What was sold and earned" },
  { href: "/dashboard/sales-flown", label: "Sales vs Flown", icon: PlaneTakeoff, blurb: "How much of it has flown" },
  { href: "/dashboard/risk", label: "Risk analysis", icon: ShieldAlert, blurb: "What could fail to arrive" },
];

export function BoardTabs() {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Revenue boards"
      className="flex gap-1 overflow-x-auto rounded-xl bg-white p-1 ring-1 ring-line shadow-sm"
    >
      {BOARDS.map((b) => {
        const active = pathname === b.href;
        const Icon = b.icon;
        return (
          <Link
            key={b.href}
            href={b.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "group flex min-w-44 flex-1 items-center gap-2.5 rounded-lg px-3 py-2 transition-colors",
              active ? "bg-brand-900 text-white shadow-sm" : "text-gray-600 hover:bg-brand-50",
            )}
          >
            <span
              className={cn(
                "flex h-7 w-7 shrink-0 items-center justify-center rounded-md",
                active ? "bg-white/15" : "bg-brand-50 text-brand-700 group-hover:bg-white",
              )}
            >
              <Icon className="h-4 w-4" aria-hidden />
            </span>
            <span className="min-w-0">
              <span className="block text-[13px] font-semibold leading-tight">{b.label}</span>
              <span className={cn("block truncate text-[11px] leading-tight", active ? "text-white/70" : "text-gray-400")}>
                {b.blurb}
              </span>
            </span>
          </Link>
        );
      })}
    </nav>
  );
}

// ── Page header ─────────────────────────────────────────────────────────────

export function BoardHeader({
  icon: Icon,
  title,
  description,
  meta,
  actions,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  /** Small context chips: currency, as-of date, scope. */
  meta?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <header className="relative overflow-hidden rounded-2xl bg-[image:var(--brand-deep)] px-5 py-5 text-white shadow-sm sm:px-6">
      {/* Quiet texture so the band does not read as a flat block of colour. */}
      <div
        className="pointer-events-none absolute -right-16 -top-24 h-64 w-64 rounded-full bg-white/5"
        aria-hidden
      />
      <div
        className="pointer-events-none absolute -bottom-24 right-40 h-48 w-48 rounded-full bg-white/5"
        aria-hidden
      />
      <div className="relative flex flex-wrap items-start gap-4">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white/10 ring-1 ring-white/20">
          <Icon className="h-5 w-5" aria-hidden />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-white/60">
            Dashboard
          </p>
          <h1 className="font-display text-2xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-1 max-w-3xl text-[13px] leading-relaxed text-white/75">{description}</p>
          {meta && <div className="mt-3 flex flex-wrap items-center gap-1.5">{meta}</div>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
    </header>
  );
}

export function MetaChip({ icon: Icon, children }: { icon?: LucideIcon; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-white/10 px-2.5 py-1 text-[11px] font-medium text-white/90 ring-1 ring-white/15">
      {Icon && <Icon className="h-3 w-3" aria-hidden />}
      {children}
    </span>
  );
}

// ── Section heading ─────────────────────────────────────────────────────────

export function SectionLabel({ children, hint }: { children: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-3 px-1 pt-2">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-gray-500">{children}</h2>
      <span className="h-px flex-1 bg-line" aria-hidden />
      {hint && <span className="text-[11px] text-gray-400">{hint}</span>}
    </div>
  );
}

// ── Panel ───────────────────────────────────────────────────────────────────

export function Panel({
  title,
  subtitle,
  actions,
  children,
  footer,
  flush = false,
  loading = false,
  className,
}: {
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  /** No body padding — for a table that should run edge to edge. */
  flush?: boolean;
  loading?: boolean;
  className?: string;
}) {
  return (
    <section className={cn("overflow-hidden rounded-2xl bg-white ring-1 ring-line shadow-sm", className)}>
      {(title || actions) && (
        <div className="flex flex-wrap items-start gap-3 border-b border-line/70 px-5 py-4">
          <div className="min-w-0 flex-1">
            {title && <h3 className="font-display text-[15px] font-semibold text-gray-900">{title}</h3>}
            {subtitle && <p className="mt-0.5 text-xs leading-relaxed text-gray-500">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={cn(!flush && "p-5", "transition-opacity", loading && "opacity-60")}>{children}</div>
      {footer && (
        <div className="border-t border-line/70 bg-paper px-5 py-2.5 text-[11px] text-gray-500">{footer}</div>
      )}
    </section>
  );
}

// ── Metric card ─────────────────────────────────────────────────────────────

export type Tone = "brand" | "emerald" | "amber" | "red" | "slate";

const TONE: Record<Tone, { icon: string; bar: string; ring: string }> = {
  brand: { icon: "bg-brand-50 text-brand-700", bar: "bg-brand-600", ring: "ring-line" },
  emerald: { icon: "bg-emerald-50 text-emerald-700", bar: "bg-emerald-600", ring: "ring-line" },
  amber: { icon: "bg-amber-50 text-amber-700", bar: "bg-amber-500", ring: "ring-amber-200" },
  red: { icon: "bg-red-50 text-red-700", bar: "bg-red-600", ring: "ring-red-200" },
  slate: { icon: "bg-slate-100 text-slate-600", bar: "bg-slate-500", ring: "ring-line" },
};

/**
 * One headline number. `hero` is the figure a board leads with — one per page — and is
 * drawn on the brand band so it reads first. `progress` (0–100) draws a thin meter under
 * the value, for a figure that is a share of something.
 */
export function Metric({
  label,
  value,
  sub,
  icon: Icon,
  tone = "brand",
  hero = false,
  loading = false,
  progress,
  className,
}: {
  label: string;
  value: string;
  sub?: React.ReactNode;
  icon?: LucideIcon;
  tone?: Tone;
  hero?: boolean;
  loading?: boolean;
  progress?: number | null;
  className?: string;
}) {
  const t = TONE[tone];
  const empty = loading && (value === "—" || value === "");
  return (
    <div
      className={cn(
        "relative flex flex-col rounded-2xl p-4 shadow-sm ring-1 transition-opacity",
        hero ? "bg-brand-900 text-white ring-brand-900" : cn("bg-white", t.ring),
        loading && "opacity-70",
        className,
      )}
    >
      <div className="flex items-center gap-2.5">
        {Icon && (
          <span
            className={cn(
              "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
              hero ? "bg-white/10 text-white" : t.icon,
            )}
          >
            <Icon className="h-4 w-4" aria-hidden />
          </span>
        )}
        <p className={cn("text-[11px] font-semibold uppercase tracking-wide", hero ? "text-white/70" : "text-gray-500")}>
          {label}
        </p>
      </div>
      {empty ? (
        <Skeleton className={cn("mt-4 h-8 w-32", hero && "bg-white/15")} />
      ) : (
        <p
          className={cn(
            "mt-3 font-display font-semibold leading-none tracking-tight",
            hero ? "text-4xl" : "text-[28px] text-gray-900",
          )}
        >
          {value}
        </p>
      )}
      {progress != null && (
        <div className={cn("mt-3 h-1.5 overflow-hidden rounded-full", hero ? "bg-white/15" : "bg-gray-100")}>
          <div
            className={cn("h-full rounded-full", hero ? "bg-white" : t.bar)}
            style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
          />
        </div>
      )}
      {sub && (
        <div className={cn("mt-auto pt-2.5 text-xs leading-snug", hero ? "text-white/75" : "text-gray-500")}>
          {sub}
        </div>
      )}
    </div>
  );
}

// ── Small pieces ────────────────────────────────────────────────────────────

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-gray-100", className)} aria-hidden />;
}

export function Notice({
  tone = "amber",
  icon: Icon,
  title,
  children,
  action,
}: {
  tone?: "amber" | "slate";
  icon?: LucideIcon;
  title: React.ReactNode;
  children?: React.ReactNode;
  action?: React.ReactNode;
}) {
  const s =
    tone === "amber"
      ? { box: "bg-amber-50 ring-amber-200", icon: "text-amber-600", title: "text-amber-900", body: "text-amber-800" }
      : { box: "bg-slate-50 ring-slate-200", icon: "text-slate-500", title: "text-slate-900", body: "text-slate-600" };
  return (
    <div className={cn("flex items-start gap-3 rounded-2xl p-4 ring-1", s.box)}>
      {Icon && <Icon className={cn("mt-0.5 h-5 w-5 shrink-0", s.icon)} aria-hidden />}
      <div className="min-w-0 flex-1">
        <p className={cn("text-sm font-semibold", s.title)}>{title}</p>
        {children && <div className={cn("mt-0.5 text-xs leading-relaxed", s.body)}>{children}</div>}
      </div>
      {action}
    </div>
  );
}

export function EmptyState({ icon: Icon, children }: { icon?: LucideIcon; children: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
      {Icon && (
        <span className="flex h-10 w-10 items-center justify-center rounded-full bg-gray-50 text-gray-400">
          <Icon className="h-5 w-5" aria-hidden />
        </span>
      )}
      <p className="max-w-sm text-sm text-gray-500">{children}</p>
    </div>
  );
}

/** Table header classes shared by every board table: quiet, sticky, uppercase. */
export const TH =
  "sticky top-0 z-[1] bg-paper px-3 py-2.5 text-[10px] font-semibold uppercase tracking-wider text-gray-500 whitespace-nowrap border-b border-line";
export const TD = "px-3 py-2 whitespace-nowrap tabular-nums";
