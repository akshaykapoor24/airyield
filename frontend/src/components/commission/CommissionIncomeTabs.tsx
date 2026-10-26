"use client";

// The tab shell for Vendors → Commission income: one tab per kind of statement priced —
// BSP · BSP-NDC · LCC · Third Party GDS · Third Party LCC · Third Party API
// (lib/commissionSources.ts COMMISSION_TABS).
//
// One row of tabs, as Vendor Reconciliation has: every tab asks the same question — that
// statement's rows against your deals — so the statement type is the only choice. Kept as
// in-page state plus a `?source=` param rather than nested routes: the detail view is already
// a state swap inside CommissionIncomeView, so routing here would give the screen two
// different navigation models.

import { useCallback, useState } from "react";
import { cn } from "@/lib/utils";
import {
  COMMISSION_SOURCES, COMMISSION_TABS, getSource, type CommissionSourceSlug,
} from "@/lib/commissionSources";
import CommissionIncomeView from "./CommissionIncomeView";

export default function CommissionIncomeTabs() {
  // Read once on mount. `?source=` makes a tab linkable — the natural thing to paste into
  // a message when asking a colleague to look at one consolidator's numbers. An unknown
  // source opens the first tab.
  const [sourceSlug, setSourceSlug] = useState<CommissionSourceSlug>(() => {
    if (typeof window === "undefined") return COMMISSION_TABS[0];
    const q = getSource(new URLSearchParams(window.location.search).get("source"))?.slug;
    return q && COMMISSION_TABS.includes(q) ? q : COMMISSION_TABS[0];
  });

  const select = useCallback((slug: CommissionSourceSlug) => {
    setSourceSlug(slug);
    const url = new URL(window.location.href);
    url.searchParams.set("source", slug);
    window.history.replaceState({}, "", url);
  }, []);

  const source = COMMISSION_SOURCES[sourceSlug];

  return (
    <div>
      <div className="mb-4">
        <h1 className="text-base font-bold text-slate-900">Commission income</h1>
        <p className="text-xs text-slate-400 mt-0.5">{source.blurb}</p>
      </div>

      <div className="flex items-center gap-1 border-b border-slate-200 mb-4 overflow-x-auto">
        {COMMISSION_TABS.map((slug) => {
          const active = slug === sourceSlug;
          return (
            <button
              key={slug}
              type="button"
              onClick={() => select(slug)}
              className={cn(
                "px-3.5 py-2 text-xs font-semibold border-b-2 -mb-px transition-colors whitespace-nowrap",
                active
                  ? "border-blue-600 text-blue-700"
                  : "border-transparent text-slate-400 hover:text-slate-700",
              )}
            >
              {COMMISSION_SOURCES[slug].label}
            </button>
          );
        })}
      </div>

      {/* `key` forces a remount per source: the picker holds a selected statement and its
          rows in state, and carrying either across a tab change would show one source's
          rows under another's heading. */}
      <CommissionIncomeView key={sourceSlug} source={source} />
    </div>
  );
}
