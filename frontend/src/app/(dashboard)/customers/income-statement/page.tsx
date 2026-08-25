"use client";

// Customer data → Income Statement.
//
// The saved per-statement income summaries. Same screen as the old
// /tickets/income-summary route — one implementation, reachable from the
// Customer data nav now that Internal Statement is no longer its own section.
//
// Deliberately NOT nested under /customers/statements: the sidebar's isActive
// matches on `pathname.startsWith(href + "/")`, so a path under there would
// light up "Statement" as well as this entry.

import IncomeSummaryTabPage from "@/app/(dashboard)/tickets/income-summary/page";

export default function CustomerIncomeStatementPage() {
  return <IncomeSummaryTabPage />;
}
