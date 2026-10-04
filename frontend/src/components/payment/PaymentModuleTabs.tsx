"use client";

// The tab shell for Vendors data → Payment Module: Vendor Statement · MO Statement ·
// Reconciliation · Payments.
//
// In-page state plus a `?tab=` param, the navigation model Commission income and Vendor
// Reconciliation already use (components/reconciliation/ReconciliationTabs.tsx), so a tab
// is linkable without nested routes. The two statement tabs are the Statements hub's own
// uploads screen pointed at two types, with its opt-in Checks column and control totals
// switched on; Reconciliation and Payments are this module's own.

import { useCallback, useState } from "react";
import { cn } from "@/lib/utils";
import AdjustmentStatementsView from "@/components/statements/AdjustmentStatementsView";
import PaymentReconciliationView from "./PaymentReconciliationView";
import PaymentsView from "./PaymentsView";
import {
  MO_CHECKS, MO_STATEMENT, PAYMENT_TABS, VENDOR_CHECKS, VENDOR_STATEMENT, getPaymentTab,
  type PaymentTabSlug,
} from "@/lib/paymentModule";
import type { StatementType } from "@/lib/statements";

function StatementTab({ type, checks }: { type: StatementType; checks: { api: string; slug: string } }) {
  return (
    <AdjustmentStatementsView
      key={type.slug}
      slug={type.slug}
      apiBase={type.apiBase ?? ""}
      title={type.label}
      blurb={type.blurb ?? ""}
      requiresSupplier={type.requiresSupplier}
      supportsMapping={type.supportsMapping}
      doneHint={type.doneHint}
      checks={checks}
      captureControls
    />
  );
}

export default function PaymentModuleTabs() {
  // Read once on mount, like ReconciliationTabs — `?tab=` is what a colleague is sent.
  const [tabSlug, setTabSlug] = useState<PaymentTabSlug>(() => {
    if (typeof window === "undefined") return "vendor";
    const q = new URLSearchParams(window.location.search).get("tab");
    return getPaymentTab(q)?.slug ?? "vendor";
  });

  const select = useCallback((slug: PaymentTabSlug) => {
    setTabSlug(slug);
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

      {/* Each view holds uploads, filters and an open drill-in in state; remounting per
          tab keeps one type's rows from ever showing under the other's heading. */}
      {tab.slug === "vendor" && <StatementTab key="vendor" type={VENDOR_STATEMENT} checks={VENDOR_CHECKS} />}
      {tab.slug === "mo" && <StatementTab key="mo" type={MO_STATEMENT} checks={MO_CHECKS} />}
      {tab.slug === "reconciliation" && (
        <PaymentReconciliationView key="reconciliation" onOpenTab={select} />
      )}
      {tab.slug === "payments" && <PaymentsView key="payments" onOpenTab={select} />}
    </div>
  );
}
