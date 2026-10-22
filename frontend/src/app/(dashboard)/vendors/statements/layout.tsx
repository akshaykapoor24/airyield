"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { cn } from "@/lib/utils";
import { STATEMENT_NAV, categoryFirstPath } from "@/lib/statements";

export default function StatementsLayout({ children }: { children: React.ReactNode }) {
  const params = useParams();
  const activeCat = (params?.category as string) ?? STATEMENT_NAV[0].slug;
  const activeType = params?.type as string | undefined;
  const category = STATEMENT_NAV.find((c) => c.slug === activeCat) ?? STATEMENT_NAV[0];

  return (
    <div className="w-full">
      {/* Title — one short line, so the statement below starts high enough to fit the screen */}
      <h1 className="mb-2 text-base font-semibold text-slate-900">Vendor statement</h1>

      {/* Category tabs */}
      <div className="flex items-center gap-1 border-b border-slate-200 mb-2.5">
        {STATEMENT_NAV.map((cat) => {
          const active = cat.slug === activeCat;
          return (
            <Link
              key={cat.slug}
              href={categoryFirstPath(cat.slug)}
              className={cn(
                "px-4 py-1.5 text-sm font-semibold border-b-2 -mb-px transition-colors",
                active
                  ? "border-blue-600 text-blue-700"
                  : "border-transparent text-slate-500 hover:text-slate-800"
              )}
            >
              {cat.label}
            </Link>
          );
        })}
      </div>

      {/* Type tabs (for the active category) */}
      <div className="flex flex-wrap items-center gap-1.5 mb-3">
        {category.types.map((t) => {
          const active = t.slug === activeType;
          return (
            <Link
              key={t.slug}
              href={`/vendors/statements/${category.slug}/${t.slug}`}
              className={cn(
                "px-3 py-1 rounded-lg text-xs font-medium border transition-colors",
                active
                  ? "bg-blue-600 border-blue-600 text-white"
                  : t.status === "coming-soon"
                    ? "bg-white border-slate-200 text-slate-400 hover:bg-slate-50 hover:text-slate-600"
                    : "bg-white border-slate-200 text-slate-600 hover:bg-slate-50 hover:text-slate-900"
              )}
            >
              {t.label}
            </Link>
          );
        })}
      </div>

      {children}
    </div>
  );
}
