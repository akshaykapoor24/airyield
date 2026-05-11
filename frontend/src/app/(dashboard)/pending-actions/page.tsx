"use client";

import Link from "next/link";
import { AlertTriangle, Clock, CheckSquare, FileText, Ticket, Edit3, ArrowRight } from "lucide-react";

const PENDING = {
  dealApprovals: [
    { id: 3, ref: "AI-CORP-25", airline: "Air India", type: "Airline Direct", submittedBy: "Pooja S.", submittedOn: "01 Apr 2025", urgency: "high" },
    { id: 6, ref: "EK-APR-NEG", airline: "Emirates", type: "Negotiated", submittedBy: "Manvendra C.", submittedOn: "01 Apr 2025", urgency: "medium" },
  ],
  extractionReview: [
    { id: 8, ref: "SG-APR-25", airline: "SpiceJet", file: "SG_April_deal.pdf", uploadedOn: "05 Apr 2025" },
    { id: 9, ref: "6E-APR-25", airline: "IndiGo", file: "IndiGo_April_circular.xlsx", uploadedOn: "05 Apr 2025" },
  ],
  unmatchedTickets: [
    { ticket: "098-1234567891", route: "DEL-CCU", airline: "IndiGo", class: "Y", date: "07 Apr 2025" },
    { ticket: "114-5552341234", route: "DEL-BOM", airline: "SpiceJet", class: "Y", date: "10 Apr 2025" },
    { ticket: "220-8877665544", route: "BOM-HYD", airline: "Air India", class: "W", date: "09 Apr 2025" },
  ],
  overrideApprovals: [
    { id: 5, ticket: "057-9876543210", passenger: "Vikram Nair", original: 46.00, override: 56.40, reason: "Special corporate rate applied", by: "Manvendra C." },
  ],
};

const URGENCY: Record<string, string> = {
  high: "bg-red-100 text-red-700",
  medium: "bg-yellow-100 text-yellow-700",
  low: "bg-gray-100 text-gray-600",
};

export default function PendingActionsPage() {
  const total = PENDING.dealApprovals.length + PENDING.extractionReview.length + PENDING.unmatchedTickets.length + PENDING.overrideApprovals.length;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Pending Actions</h1>
        <p className="text-sm text-gray-500 mt-0.5">{total} items require your attention</p>
      </div>

      {/* Summary Pills */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: "Deal Approvals", count: PENDING.dealApprovals.length, icon: CheckSquare, color: "text-blue-600 bg-blue-50", href: "/deals/approvals" },
          { label: "Extraction Review", count: PENDING.extractionReview.length, icon: FileText, color: "text-purple-600 bg-purple-50", href: "/deals/review" },
          { label: "Unmatched Tickets", count: PENDING.unmatchedTickets.length, icon: Ticket, color: "text-orange-600 bg-orange-50", href: "/calculations/exceptions" },
          { label: "Override Approvals", count: PENDING.overrideApprovals.length, icon: Edit3, color: "text-red-600 bg-red-50", href: "/calculations/override-approval" },
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
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-xs uppercase text-gray-500">
            <tr>
              <th className="px-5 py-3 text-left">Reference</th>
              <th className="px-5 py-3 text-left">Airline</th>
              <th className="px-5 py-3 text-left">Type</th>
              <th className="px-5 py-3 text-left">Submitted By</th>
              <th className="px-5 py-3 text-left">Date</th>
              <th className="px-5 py-3 text-left">Urgency</th>
              <th className="px-5 py-3 text-center">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {PENDING.dealApprovals.map((d) => (
              <tr key={d.id} className="hover:bg-gray-50">
                <td className="px-5 py-3 font-mono text-xs text-blue-600">{d.ref}</td>
                <td className="px-5 py-3 font-medium">{d.airline}</td>
                <td className="px-5 py-3 text-gray-500">{d.type}</td>
                <td className="px-5 py-3 text-gray-500">{d.submittedBy}</td>
                <td className="px-5 py-3 text-gray-500">{d.submittedOn}</td>
                <td className="px-5 py-3"><span className={`px-2 py-0.5 rounded-full text-xs font-medium capitalize ${URGENCY[d.urgency]}`}>{d.urgency}</span></td>
                <td className="px-5 py-3 text-center">
                  <Link href={`/deals/${d.id}`} className="text-xs bg-blue-600 text-white px-3 py-1 rounded-lg hover:bg-blue-700">Review</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Extraction Review */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-2"><FileText className="w-4 h-4 text-purple-500" /> Deals Awaiting Extraction Review</h2>
          <Link href="/deals/review" className="text-xs text-blue-600 hover:underline flex items-center gap-1">View all <ArrowRight className="w-3 h-3" /></Link>
        </div>
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
            {PENDING.extractionReview.map((d) => (
              <tr key={d.id} className="hover:bg-gray-50">
                <td className="px-5 py-3 font-mono text-xs text-purple-600">{d.ref}</td>
                <td className="px-5 py-3 font-medium">{d.airline}</td>
                <td className="px-5 py-3 text-gray-500">{d.file}</td>
                <td className="px-5 py-3 text-gray-500">{d.uploadedOn}</td>
                <td className="px-5 py-3 text-center">
                  <Link href="/deals/review" className="text-xs bg-purple-600 text-white px-3 py-1 rounded-lg hover:bg-purple-700">Review</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Unmatched Tickets */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-2"><AlertTriangle className="w-4 h-4 text-orange-500" /> Unmatched Tickets</h2>
          <Link href="/calculations/exceptions" className="text-xs text-blue-600 hover:underline flex items-center gap-1">View all <ArrowRight className="w-3 h-3" /></Link>
        </div>
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-xs uppercase text-gray-500">
            <tr>
              <th className="px-5 py-3 text-left">Ticket #</th>
              <th className="px-5 py-3 text-left">Airline</th>
              <th className="px-5 py-3 text-left">Route</th>
              <th className="px-5 py-3 text-left">Class</th>
              <th className="px-5 py-3 text-left">Travel Date</th>
              <th className="px-5 py-3 text-center">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {PENDING.unmatchedTickets.map((t) => (
              <tr key={t.ticket} className="hover:bg-gray-50">
                <td className="px-5 py-3 font-mono text-xs">{t.ticket}</td>
                <td className="px-5 py-3 font-medium">{t.airline}</td>
                <td className="px-5 py-3">{t.route}</td>
                <td className="px-5 py-3"><span className="bg-gray-100 px-2 py-0.5 rounded text-xs font-medium">{t.class}</span></td>
                <td className="px-5 py-3 text-gray-500">{t.date}</td>
                <td className="px-5 py-3 text-center">
                  <Link href="/calculations/exceptions" className="text-xs bg-orange-600 text-white px-3 py-1 rounded-lg hover:bg-orange-700">Match</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
