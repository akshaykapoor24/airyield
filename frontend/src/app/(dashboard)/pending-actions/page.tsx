"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, CheckSquare, FileText, Ticket, ArrowRight, RefreshCw } from "lucide-react";
import api from "@/lib/api";

type DealApprovalItem    = { id: number; deal_id: number; deal_ref: string; airline_name: string; deal_type: string; submitted_by: string; submitted_at: string };
type ExtractionReviewItem = { id: number; deal_ref: string; airline_name: string; file_name: string; uploaded_at: string };
type UnmatchedTicketItem  = { id: number; ticket_number: string | null; airlines_code: string | null; airline_name: string | null; sector: string | null; booking_class: string | null; ticket_date: string | null };

type PendingActionsData = {
  deal_approvals:    DealApprovalItem[];
  extraction_review: ExtractionReviewItem[];
  unmatched_tickets: UnmatchedTicketItem[];
};

export default function PendingActionsPage() {
  const [data,    setData]    = useState<PendingActionsData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get<PendingActionsData>("/dashboard/pending-actions")
      .then(r => setData(r.data))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">
        <RefreshCw className="w-5 h-5 animate-spin mr-2" /> Loading…
      </div>
    );
  }

  const d = data ?? { deal_approvals: [], extraction_review: [], unmatched_tickets: [] };
  const total = d.deal_approvals.length + d.extraction_review.length + d.unmatched_tickets.length;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Pending Actions</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          {total === 0 ? "All caught up — nothing pending." : `${total} item${total !== 1 ? "s" : ""} require your attention`}
        </p>
      </div>

      {/* Summary Pills */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {[
          { label: "Deal Approvals",    count: d.deal_approvals.length,    icon: CheckSquare, color: "text-blue-600 bg-blue-50",   href: "/deals/approvals" },
          { label: "Extraction Review", count: d.extraction_review.length, icon: FileText,    color: "text-purple-600 bg-purple-50", href: "/deals" },
          { label: "Unmatched Tickets", count: d.unmatched_tickets.length, icon: Ticket,      color: "text-orange-600 bg-orange-50", href: "/tickets" },
        ].map(({ label, count, icon: Icon, color, href }) => (
          <Link key={label} href={href} className="bg-white rounded-xl border border-gray-200 p-5 flex items-center gap-4 hover:border-blue-300 transition-colors">
            <div className={`p-3 rounded-lg ${color}`}><Icon className="w-5 h-5" /></div>
            <div>
              <p className="text-2xl font-bold text-gray-900">{count}</p>
              <p className="text-xs text-gray-500">{label}</p>
            </div>
          </Link>
        ))}
      </div>

      {/* Deal Approvals */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-2"><CheckSquare className="w-4 h-4 text-blue-500" /> Deal Approvals Pending</h2>
          <Link href="/deals/approvals" className="text-xs text-blue-600 hover:underline flex items-center gap-1">View all <ArrowRight className="w-3 h-3" /></Link>
        </div>
        {d.deal_approvals.length === 0 ? (
          <div className="px-5 py-8 text-center text-xs text-gray-400">No pending deal approvals</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-xs uppercase text-gray-500">
              <tr>
                <th className="px-5 py-3 text-left">Reference</th>
                <th className="px-5 py-3 text-left">Airline</th>
                <th className="px-5 py-3 text-left">Type</th>
                <th className="px-5 py-3 text-left">Submitted By</th>
                <th className="px-5 py-3 text-left">Date</th>
                <th className="px-5 py-3 text-center">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {d.deal_approvals.map((a) => (
                <tr key={a.id} className="hover:bg-gray-50">
                  <td className="px-5 py-3 font-mono text-xs text-blue-600">{a.deal_ref}</td>
                  <td className="px-5 py-3 font-medium">{a.airline_name}</td>
                  <td className="px-5 py-3 text-gray-500 capitalize">{a.deal_type}</td>
                  <td className="px-5 py-3 text-gray-500">{a.submitted_by}</td>
                  <td className="px-5 py-3 text-gray-500">{a.submitted_at}</td>
                  <td className="px-5 py-3 text-center">
                    <Link href={`/deals/approvals`} className="text-xs bg-blue-600 text-white px-3 py-1 rounded-lg hover:bg-blue-700">Review</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Extraction Review */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-2"><FileText className="w-4 h-4 text-purple-500" /> Deals Awaiting Review</h2>
          <Link href="/deals" className="text-xs text-blue-600 hover:underline flex items-center gap-1">View all <ArrowRight className="w-3 h-3" /></Link>
        </div>
        {d.extraction_review.length === 0 ? (
          <div className="px-5 py-8 text-center text-xs text-gray-400">No deals awaiting review</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-xs uppercase text-gray-500">
              <tr>
                <th className="px-5 py-3 text-left">Reference</th>
                <th className="px-5 py-3 text-left">Airline</th>
                <th className="px-5 py-3 text-left">Source File</th>
                <th className="px-5 py-3 text-left">Uploaded On</th>
                <th className="px-5 py-3 text-center">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {d.extraction_review.map((r) => (
                <tr key={r.id} className="hover:bg-gray-50">
                  <td className="px-5 py-3 font-mono text-xs text-purple-600">{r.deal_ref}</td>
                  <td className="px-5 py-3 font-medium">{r.airline_name}</td>
                  <td className="px-5 py-3 text-gray-500 text-xs">{r.file_name}</td>
                  <td className="px-5 py-3 text-gray-500">{r.uploaded_at}</td>
                  <td className="px-5 py-3 text-center">
                    <Link href="/deals" className="text-xs bg-purple-600 text-white px-3 py-1 rounded-lg hover:bg-purple-700">Review</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Unmatched Tickets */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-2"><AlertTriangle className="w-4 h-4 text-orange-500" /> Unmatched Tickets</h2>
          <Link href="/tickets" className="text-xs text-blue-600 hover:underline flex items-center gap-1">View all <ArrowRight className="w-3 h-3" /></Link>
        </div>
        {d.unmatched_tickets.length === 0 ? (
          <div className="px-5 py-8 text-center text-xs text-gray-400">All tickets matched</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-xs uppercase text-gray-500">
              <tr>
                <th className="px-5 py-3 text-left">Ticket #</th>
                <th className="px-5 py-3 text-left">Airline</th>
                <th className="px-5 py-3 text-left">Sector</th>
                <th className="px-5 py-3 text-left">Class</th>
                <th className="px-5 py-3 text-left">Ticket Date</th>
                <th className="px-5 py-3 text-center">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {d.unmatched_tickets.map((t) => (
                <tr key={t.id} className="hover:bg-gray-50">
                  <td className="px-5 py-3 font-mono text-xs">{t.ticket_number ?? `#${t.id}`}</td>
                  <td className="px-5 py-3 font-medium">{t.airline_name || t.airlines_code || "—"}</td>
                  <td className="px-5 py-3 text-gray-500">{t.sector ?? "—"}</td>
                  <td className="px-5 py-3"><span className="bg-gray-100 px-2 py-0.5 rounded text-xs font-medium">{t.booking_class ?? "—"}</span></td>
                  <td className="px-5 py-3 text-gray-500">{t.ticket_date ?? "—"}</td>
                  <td className="px-5 py-3 text-center">
                    <Link href="/tickets" className="text-xs bg-orange-600 text-white px-3 py-1 rounded-lg hover:bg-orange-700">View</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
