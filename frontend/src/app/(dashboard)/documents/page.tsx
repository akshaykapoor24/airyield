"use client";

import { useState } from "react";
import { FileText, Image, Mail, Download, Trash2, Upload, Search } from "lucide-react";

const MOCK_DOCS = [
  { id: 1, name: "EK_Q2_2025_deal_sheet.pdf", category: "deal_pdf", deal: "EK-Q2-2025", size: "420 KB", uploaded_by: "Manvendra C.", date: "22 Mar 2025", mime: "application/pdf" },
  { id: 2, name: "EK_email_confirmation.pdf", category: "email", deal: "EK-Q2-2025", size: "85 KB", uploaded_by: "Manvendra C.", date: "22 Mar 2025", mime: "application/pdf" },
  { id: 3, name: "IndiGo_March_standard.xlsx", category: "deal_excel", deal: "6E-MAR-25", size: "210 KB", uploaded_by: "Pooja S.", date: "01 Mar 2025", mime: "application/vnd.ms-excel" },
  { id: 4, name: "AI_CORP_screenshot.png", category: "screenshot", deal: "AI-CORP-25", size: "1.2 MB", uploaded_by: "Rajesh K.", date: "01 Apr 2025", mime: "image/png" },
  { id: 5, name: "SpiceJet_Q1_deal.pdf", category: "deal_pdf", deal: "SG-Q1-25", size: "340 KB", uploaded_by: "Pooja S.", date: "02 Jan 2025", mime: "application/pdf" },
  { id: 6, name: "April_tickets_batch1.xlsx", category: "ticket_upload", deal: null, size: "890 KB", uploaded_by: "Manvendra C.", date: "05 Apr 2025", mime: "application/vnd.ms-excel" },
  { id: 7, name: "Vistara_promo_email.pdf", category: "email", deal: "UK-MAR-OT", size: "62 KB", uploaded_by: "Rajesh K.", date: "14 Mar 2025", mime: "application/pdf" },
  { id: 8, name: "EK_April_negotiated_v2.pdf", category: "deal_pdf", deal: "EK-APR-NEG", size: "505 KB", uploaded_by: "Manvendra C.", date: "01 Apr 2025", mime: "application/pdf" },
];

const CATEGORY_LABELS: Record<string, string> = {
  deal_pdf: "Deal PDF",
  deal_excel: "Deal Excel",
  email: "Email",
  screenshot: "Screenshot",
  ticket_upload: "Ticket Upload",
  other: "Other",
};

const CATEGORY_COLORS: Record<string, string> = {
  deal_pdf: "bg-blue-100 text-blue-700",
  deal_excel: "bg-green-100 text-green-700",
  email: "bg-purple-100 text-purple-700",
  screenshot: "bg-orange-100 text-orange-700",
  ticket_upload: "bg-teal-100 text-teal-700",
  other: "bg-gray-100 text-gray-600",
};

function FileIcon({ mime }: { mime: string }) {
  if (mime.includes("image")) return <Image className="w-5 h-5 text-orange-400" />;
  if (mime.includes("pdf")) return <FileText className="w-5 h-5 text-red-400" />;
  return <FileText className="w-5 h-5 text-green-500" />;
}

export default function DocumentsPage() {
  const [docs, setDocs] = useState(MOCK_DOCS);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");

  const filtered = docs.filter((d) => {
    const matchSearch = d.name.toLowerCase().includes(search.toLowerCase()) || (d.deal || "").toLowerCase().includes(search.toLowerCase());
    const matchFilter = filter === "all" || d.category === filter;
    return matchSearch && matchFilter;
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Documents</h1>
          <p className="text-sm text-gray-500 mt-0.5">{docs.length} files stored</p>
        </div>
        <button className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700">
          <Upload className="w-4 h-4" /> Upload Document
        </button>
      </div>

      {/* Search + Filter */}
      <div className="flex gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name or deal..."
            className="w-full pl-9 pr-4 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-600 focus:outline-none"
        >
          <option value="all">All Types</option>
          {Object.entries(CATEGORY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>

      {/* Grid View */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {filtered.map((doc) => (
          <div key={doc.id} className="bg-white rounded-xl border border-gray-200 p-4 hover:border-blue-300 transition-colors group">
            <div className="flex items-start justify-between mb-3">
              <div className="p-2 bg-gray-50 rounded-lg">
                <FileIcon mime={doc.mime} />
              </div>
              <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <button className="p-1 hover:bg-gray-100 rounded"><Download className="w-3.5 h-3.5 text-gray-500" /></button>
                <button onClick={() => setDocs((d) => d.filter((x) => x.id !== doc.id))} className="p-1 hover:bg-red-50 rounded">
                  <Trash2 className="w-3.5 h-3.5 text-red-400" />
                </button>
              </div>
            </div>
            <p className="text-sm font-medium text-gray-800 truncate" title={doc.name}>{doc.name}</p>
            <div className="mt-2 flex items-center gap-2">
              <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${CATEGORY_COLORS[doc.category]}`}>
                {CATEGORY_LABELS[doc.category]}
              </span>
            </div>
            <div className="mt-3 text-xs text-gray-400 space-y-0.5">
              {doc.deal && <p>Deal: <span className="text-gray-600 font-mono">{doc.deal}</span></p>}
              <p>{doc.size} · {doc.date}</p>
              <p>by {doc.uploaded_by}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
