"use client";

// The tab shell for Vendors → Commission income: BSP · LCC · Third Party, with an inner
// GDS/LCC switch for Third Party.
//
// Two rows of tabs, mirroring the Statements page (app/(dashboard)/vendors/statements),
// because they are the same two questions in the same order — which family, then which
// document. Kept as in-page state plus a `?source=` param rather than nested routes: the
// detail view is already a state swap inside CommissionIncomeView, so routing here would
// give the screen two different navigation models.

import { useCallback, useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import {
  COMMISSION_SOURCES, COMMISSION_TABS, getSource, tabForSource,
  type CommissionSourceSlug,
} from "@/lib/commissionSources";
import CommissionIncomeView from "./CommissionIncomeView";

export default function CommissionIncomeTabs() {
  // Read once on mount. `?source=` makes a tab linkable — the natural thing to paste into
  // a message when asking a colleague to look at one consolidator's numbers.
  const [sourceSlug, setSourceSlug] = useState<CommissionSourceSlug>(() => {
    if (typeof window === "undefined") return "bsp";
    const q = new URLSearchParams(window.location.search).get("source");
    return (getSource(q)?.slug ?? "bsp") as CommissionSourceSlug;
  });

  const select = useCallback((slug: CommissionSourceSlug) => {
    setSourceSlug(slug);
    const url = new URL(window.location.href);
    url.searchParams.set("source", slug);
    window.history.replaceState({}, "", url);
  }, []);

  const source = COMMISSION_SOURCES[sourceSlug];
  const tab = tabForSource(sourceSlug);

  // Opening a different tab should land on its first source, not on whatever was picked
  // inside it last time.
  const openTab = (slug: string) => {
    const t = COMMISSION_TABS.find((x) => x.slug === slug);
    if (t) select(t.sources[0]);
  };

  useEffect(() => {
    if (!COMMISSION_SOURCES[sourceSlug]) setSourceSlug("bsp");
  }, [sourceSlug]);

  return (
    <div>
      <div className="mb-4">
        <h1 className="text-base font-bold text-slate-900">Commission income</h1>
        <p className="text-xs text-slate-400 mt-0.5">{source.blurb}</p>
      </div>

      {/* Family */}
      <div className="flex items-center gap-1 border-b border-slate-200 mb-3">
        {COMMISSION_TABS.map((t) => {
          const active = t.slug === tab.slug;
          return (
            <button
              key={t.slug}
              type="button"
              onClick={() => openTab(t.slug)}
              className={cn(
                "px-3.5 py-2 text-xs font-semibold border-b-2 -mb-px transition-colors",
                active
                  ? "border-blue-600 text-blue-700"
                  : "border-transparent text-slate-400 hover:text-slate-700",
              )}
            >
              {t.label}
            </button>
          );
        })}
      </div>

      {/* Document, when the family holds more than one */}
      {tab.sources.length > 1 && (
        <div className="flex items-center gap-1.5 mb-4">
          {tab.sources.map((slug) => {
            const s = COMMISSION_SOURCES[slug];
            const active = slug === sourceSlug;
            return (
              <button
                key={slug}
                type="button"
                onClick={() => select(slug)}
                className={cn(
                  "px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors",
                  active
                    ? "bg-blue-50 border-blue-300 text-blue-700"
                    : "bg-white border-slate-200 text-slate-500 hover:bg-slate-50 hover:text-slate-800",
                )}
              >
                {s.label}
              </button>
            );
          })}
        </div>
      )}

      {/* `key` forces a remount per source: the picker holds a selected statement and its
          rows in state, and carrying either across a tab change would show one source's
          rows under another's heading. */}
      <CommissionIncomeView key={sourceSlug} source={source} />
    </div>
  );
}
