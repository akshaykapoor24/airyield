"use client";

import { cn } from "@/lib/utils";

/**
 * Stat tile: label, value, optional sub-line.
 *
 * `hero` is for the one number a view leads with — exactly one per page. Values
 * use the font's proportional figures deliberately: `tabular-nums` gives every
 * digit the width of a zero, which makes a large standalone number look loose.
 * Tabular figures belong in the grid's columns, not here.
 */
export default function KpiTile({
  label,
  value,
  sub,
  hero = false,
  tone = "default",
  loading = false,
  children,
}: {
  label: string;
  value: string;
  sub?: React.ReactNode;
  hero?: boolean;
  tone?: "default" | "warning" | "danger";
  loading?: boolean;
  children?: React.ReactNode;
}) {
  const toneRing =
    tone === "danger" ? "ring-red-200 bg-red-50/40"
    : tone === "warning" ? "ring-amber-200 bg-amber-50/40"
    : "ring-gray-200 bg-white";

  return (
    <div
      className={cn(
        "rounded-xl ring-1 p-4 flex flex-col justify-between transition-opacity",
        toneRing,
        hero && "sm:col-span-2",
        loading && "opacity-60",
      )}
    >
      <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide">
        {label}
      </p>
      <p
        className={cn(
          "font-semibold text-gray-900 mt-1.5 leading-none",
          hero ? "text-4xl sm:text-5xl" : "text-2xl",
        )}
      >
        {value}
      </p>
      {sub && <div className="text-xs text-gray-500 mt-2 leading-snug">{sub}</div>}
      {children}
    </div>
  );
}
