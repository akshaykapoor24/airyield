"use client";

// The tab shell for Vendors data → Payment Module: Vendor Statement · MO Statement ·
// Vendor Mapping · Vendor Payments.
//
// In-page state plus a `?tab=` param, the navigation model Commission income and Vendor
// Reconciliation already use (components/reconciliation/ReconciliationTabs.tsx), so a tab
// is linkable without nested routes. The two statement tabs list uploads made elsewhere,
// read-only: the vendors' statements are the Statements hub's Third Party GDS and LCC uploads,
// the MO is Internal Statement's Booking / MO uploads. Vendor Mapping and Vendor Payments are
// this module's own (backend/app/services/vendor_mapping.py).

import { useCallback, useState } from "react";
import { cn } from "@/lib/utils";
import AdjustmentStatementsView from "@/components/statements/AdjustmentStatementsView";
import StatementsView from "@/components/tickets/StatementsView";
import VendorMappingView from "./VendorMappingView";
import VendorPaymentsView from "./VendorPaymentsView";
import {
  MO_UPLOAD_HREF, PAYMENT_TABS, VENDOR_CHECKS, VENDOR_GDS, VENDOR_GDS_HREF, VENDOR_LCC, VENDOR_LCC_HREF,
  getPaymentTab, type PaymentTabSlug,
} from "@/lib/paymentModule";

type Focus = { vendor?: string | null; statement?: string | null } | null;

/** Third Party GDS and LCC, one at a time — each the Statements hub's own uploads list. */
function VendorStatementTab() {
  const [kind, setKind] = useState<"gds" | "lcc">("gds");
  const t = kind === "gds" ? VENDOR_GDS : VENDOR_LCC;
  return (
    <div>
      <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5 mb-4" role="tablist">
        {(["gds", "lcc"] as const).map((k) => (
          <button key={k} type="button" role="tab" aria-selected={kind === k} onClick={() => setKind(k)}
            className={cn("px-4 py-1.5 text-xs font-semibold rounded-md transition-colors",
              kind === k ? "bg-[#1e3a5f] text-white" : "text-slate-500 hover:text-slate-800")}>
            {k === "gds" ? "GDS" : "LCC"}
          </button>
        ))}
      </div>
      <AdjustmentStatementsView
        key={t.slug}
        slug={t.slug}
        apiBase={t.apiBase ?? ""}
        title={t.label}
        blurb={t.blurb ?? ""}
        requiresSupplier={t.requiresSupplier}
        supportsMapping={t.supportsMapping}
        capturesPeriod={t.capturesPeriod}
        // LCC uploads record no control totals, so they have no completeness checks.
        checks={kind === "gds" ? VENDOR_CHECKS : undefined}
        uploadedElsewhere={kind === "gds"
          ? { href: VENDOR_GDS_HREF, label: "Statements → Third Party → GDS" }
          : { href: VENDOR_LCC_HREF, label: "Statements → Third Party → LCC" }}
      />
    </div>
  );
}

export default function PaymentModuleTabs() {
  // Read once on mount, like ReconciliationTabs — `?tab=` is what a colleague is sent.
  const [tabSlug, setTabSlug] = useState<PaymentTabSlug>(() => {
    if (typeof window === "undefined") return "vendor";
    const q = new URLSearchParams(window.location.search).get("tab");
    return getPaymentTab(q)?.slug ?? "vendor";
  });
  // The vendor (and statement) one tab hands to the next — "Pay this vendor", "Map".
  const [focus, setFocus] = useState<Focus>(null);

  const select = useCallback((slug: PaymentTabSlug, next?: Focus) => {
    setTabSlug(slug);
    setFocus(next ?? null);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", slug);
    window.history.replaceState({}, "", url);
  }, []);

  const tab = getPaymentTab(tabSlug) ?? PAYMENT_TABS[0];

  return (
    <div className="w-full">
      <div className="mb-4">
        <h1 className="text-xl font-bold text-slate-900">Payment Module</h1>
        <p className="text-xs text-slate-400 mt-0.5">{tab.blurb}</p>
      </div>

      <div className="flex items-center gap-1 border-b border-slate-200 mb-5">
        {PAYMENT_TABS.map((t) => {
          const active = t.slug === tab.slug;
          return (
            <button
              key={t.slug}
              type="button"
              onClick={() => select(t.slug)}
              className={cn(
                "px-4 py-2 text-sm font-semibold border-b-2 -mb-px transition-colors",
                active
                  ? "border-blue-600 text-blue-700"
                  : "border-transparent text-slate-500 hover:text-slate-800",
              )}
            >
              {t.label}
            </button>
          );
        })}
      </div>

      {/* Each view holds its filters and an open drill-in in state; remounting per tab (and
          per hand-off) keeps one scope's rows from ever showing under another's heading. */}
      {tab.slug === "vendor" && <VendorStatementTab key="vendor" />}
      {tab.slug === "mo" && (
        <StatementsView
          key="mo"
          showCustomer
          apiBase="/internal-tickets"
          excludeManual
          detailBaseOverride="/internal-statement/statements"
          category="booking"
          uploadedElsewhere={{ href: MO_UPLOAD_HREF, label: "Internal Statement → Upload Statement (Statement Type: Booking / MO)" }}
        />
      )}
      {tab.slug === "mapping" && (
        <VendorMappingView key={`mapping:${focus?.vendor ?? ""}:${focus?.statement ?? ""}`} onOpenTab={select} focus={focus} />
      )}
      {tab.slug === "payments" && (
        <VendorPaymentsView key={`payments:${focus?.vendor ?? ""}`} onOpenTab={select} focus={focus} />
      )}
    </div>
  );
}
