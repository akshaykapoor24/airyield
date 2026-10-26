"use client";

// The tab shell for Reconciliation → Vendor Reconciliation: one tab per kind of vendor
// statement — BSP · BSP-NDC · LCC · Third Party GDS · Third Party LCC.
//
// One row of tabs, not a family row and a document row: every tab asks the same question —
// that vendor's statement against the tickets you sold — so the statement type is the only
// choice. Kept as in-page state plus a `?source=` param rather than nested routes, so this
// screen keeps the one navigation model its neighbours use. The tabs and what each shows are
// lib/reconciliationSources.ts RECON_TABS.

import { useCallback, useState } from "react";
import { cn } from "@/lib/utils";
import { RECON_SOURCES, RECON_TABS, getReconTab, type ReconTabSlug } from "@/lib/reconciliationSources";
import ReconciliationView from "./ReconciliationView";
import VendorInternalRecon from "./VendorInternalRecon";

export default function ReconciliationTabs() {
  // Read once on mount. `?source=` makes a tab linkable — the natural thing to paste into a
  // message when asking a colleague to look at one consolidator's statement.
  const [slug, setSlug] = useState<ReconTabSlug>(() => {
    if (typeof window === "undefined") return RECON_TABS[0].slug;
    return getReconTab(new URLSearchParams(window.location.search).get("source"))?.slug ?? RECON_TABS[0].slug;
  });

  const select = useCallback((next: ReconTabSlug) => {
    setSlug(next);
    const url = new URL(window.location.href);
    url.searchParams.set("source", next);
    window.history.replaceState({}, "", url);
  }, []);

  const tab = getReconTab(slug) ?? RECON_TABS[0];
  const source = tab.view.kind === "source" ? RECON_SOURCES[tab.view.source] : undefined;

  return (
    <div>
      <div className="mb-4">
        {/* Named for its side: the sidebar's Reconciliation group holds both this and
            Customer Reconciliation, and the heading should match the entry clicked. */}
        <h1 className="text-base font-bold text-slate-900">Vendor Reconciliation</h1>
        <p className="text-xs text-slate-400 mt-0.5">{tab.blurb ?? source?.blurb}</p>
      </div>

      <div className="flex items-center gap-1 border-b border-slate-200 mb-4 overflow-x-auto">
        {RECON_TABS.map((t) => {
          const active = t.slug === tab.slug;
          return (
            <button
              key={t.slug}
              type="button"
              onClick={() => select(t.slug)}
              className={cn(
                "px-3.5 py-2 text-xs font-semibold border-b-2 -mb-px transition-colors whitespace-nowrap",
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

      {/* `key` forces a remount per tab: the view holds rows, filters and an open drilldown
          in state, and carrying any of them across a tab change would show one statement's
          numbers under another's heading. */}
      {source
        ? <ReconciliationView key={tab.slug} source={source} />
        : <VendorInternalRecon key={tab.slug} />}
    </div>
  );
}
