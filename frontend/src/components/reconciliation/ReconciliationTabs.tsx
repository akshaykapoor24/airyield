"use client";

// The tab shell for Vendors → Reconciliation: BSP · LCC · Third Party, with inner switches
// for BSP (BSP/NDC) and Third Party (GDS/LCC).
//
// Two rows of tabs, mirroring the Statements and Commission income pages, because they are
// the same two questions in the same order — which family, then which document. Kept as
// in-page state plus a `?source=` param rather than nested routes, so this screen keeps the
// one navigation model its neighbours use.

import { useCallback, useState } from "react";
import { cn } from "@/lib/utils";
import {
  RECON_SOURCES, RECON_TABS, getReconSource, tabForReconSource,
  type ReconSourceSlug,
} from "@/lib/reconciliationSources";
import ReconciliationView from "./ReconciliationView";

export default function ReconciliationTabs() {
  // Read once on mount. `?source=` makes a tab linkable — the natural thing to paste into a
  // message when asking a colleague to look at one consolidator's margins.
  const [sourceSlug, setSourceSlug] = useState<ReconSourceSlug>(() => {
    if (typeof window === "undefined") return "bsp";
    const q = new URLSearchParams(window.location.search).get("source");
    return (getReconSource(q)?.slug ?? "bsp") as ReconSourceSlug;
  });

  const select = useCallback((slug: ReconSourceSlug) => {
    setSourceSlug(slug);
    const url = new URL(window.location.href);
    url.searchParams.set("source", slug);
    window.history.replaceState({}, "", url);
  }, []);

  const source = RECON_SOURCES[sourceSlug];
  const tab = tabForReconSource(sourceSlug);

  // Opening a different tab should land on its first source, not on whatever was picked
  // inside it last time.
  const openTab = (slug: string) => {
    const t = RECON_TABS.find((x) => x.slug === slug);
    if (t) select(t.sources[0]);
  };

  // No effect resetting an unknown slug: the initializer already falls back to "bsp" via
  // getReconSource, and `select` only ever takes a slug from the registry, so `sourceSlug`
  // cannot become invalid. This guard is the belt to that pair of braces.
  if (!source) return null;

  return (
    <div>
      <div className="mb-4">
        {/* Named for its side: the sidebar's Reconciliation group holds both this and
            Customer Reconciliation, and the heading should match the entry clicked. */}
        <h1 className="text-base font-bold text-slate-900">Vendor Reconciliation</h1>
        <p className="text-xs text-slate-400 mt-0.5">{source.blurb}</p>
      </div>

      {/* Family */}
      <div className="flex items-center gap-1 border-b border-slate-200 mb-3">
        {RECON_TABS.map((t) => {
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

      {/* Document, when the family holds more than one. LCC has a single source, so it
          shows no second row — a switch with one option is noise. */}
      {tab.sources.length > 1 && (
        <div className="flex items-center gap-1.5 mb-4">
          {tab.sources.map((slug) => {
            const s = RECON_SOURCES[slug];
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

      {/* `key` forces a remount per source: the view holds rows, filters and an open
          drilldown in state, and carrying any of them across a tab change would show one
          source's numbers under another's heading. */}
      <ReconciliationView key={sourceSlug} source={source} />
    </div>
  );
}
