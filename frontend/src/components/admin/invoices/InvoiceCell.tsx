"use client";

import { FilePlus2 } from "lucide-react";
import { rupees } from "@/lib/money";
import type { InvoiceSummary } from "./shared";

/**
 * The Subscriptions table's Invoice column: Generate, and under it where this workspace
 * stands — what it owes, and whether any of it is overdue. The summary opens the history.
 */
export default function InvoiceCell({ summary, onGenerate, onHistory }: {
  /** null when the server could not read invoices; the column still offers Generate. */
  summary: InvoiceSummary | null;
  onGenerate: () => void;
  onHistory: () => void;
}) {
  const hasHistory = !!summary?.last_number;
  return (
    <td className="px-4 py-3">
      <button
        onClick={onGenerate}
        className="inline-flex items-center gap-1.5 whitespace-nowrap border border-violet-200 bg-violet-50 text-violet-700 hover:bg-violet-100 px-2.5 py-1 rounded-lg text-[11px] font-medium"
      >
        <FilePlus2 className="w-3 h-3" /> Generate
      </button>
      {hasHistory ? (
        <button onClick={onHistory} className="block mt-1 text-left text-[10px] text-gray-500 hover:text-violet-700 hover:underline whitespace-nowrap">
          {summary!.count} invoice{summary!.count !== 1 ? "s" : ""}
          {" · "}
          {summary!.unpaid_count > 0
            ? <span className="text-amber-600">{rupees(summary!.unpaid_total)} due</span>
            : "all paid"}
          {summary!.overdue_count > 0 && <span className="text-red-600"> · {summary!.overdue_count} overdue</span>}
        </button>
      ) : (
        <p className="mt-1 text-[10px] text-gray-300 whitespace-nowrap">No invoices yet</p>
      )}
    </td>
  );
}
