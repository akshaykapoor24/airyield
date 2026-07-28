"use client";

// Uploaded Documents — every file pushed to the GCP buckets across all upload features
// (Internal & Customer statements, BSP + Summary, ADM/ACM/RA, Vendor statements, Deals),
// combined into one list. Data comes from GET /documents/uploaded; files open via a
// short-lived signed URL from GET /documents/uploaded/file-url.

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  FileText, FileSpreadsheet, Download, Eye, Search, RefreshCw,
  AlertCircle, FolderOpen, X, ExternalLink,
} from "lucide-react";
import api from "@/lib/api";

type UploadedDoc = {
  id:           string;
  source_key:   string;
  ref_id:       string;
  source_label: string;
  category:     string;
  file_name:    string;
  reference:    string | null;
  uploaded_at:  string | null;
  uploaded_by:  string | null;
  link:         string | null;
};

const CATEGORY_COLORS: Record<string, string> = {
  Internal:    "bg-blue-100 text-blue-700",
  Customer:    "bg-indigo-100 text-indigo-700",
  BSP:         "bg-teal-100 text-teal-700",
  Adjustments: "bg-amber-100 text-amber-700",
  Vendor:      "bg-purple-100 text-purple-700",
  Deals:       "bg-green-100 text-green-700",
};

function formatDate(d: string | null) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

function FileIcon({ name }: { name: string }) {
  return name.toLowerCase().endsWith(".pdf")
    ? <FileText className="w-4 h-4 text-red-400" />
    : <FileSpreadsheet className="w-4 h-4 text-green-500" />;
}

export default function DocumentsPage() {
  const [docs, setDocs] = useState<UploadedDoc[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("all");

  const fetchDocs = async () => {
    setLoading(true); setError(null);
    try {
      const { data } = await api.get<UploadedDoc[]>("/documents/uploaded");
      setDocs(data);
    } catch {
      setError("Failed to load uploaded documents.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchDocs(); }, []);

  const categories = useMemo(
    () => Array.from(new Set(docs.map(d => d.category))).sort(),
    [docs],
  );

  const filtered = docs.filter(d => {
    const q = search.toLowerCase();
    const matchSearch = !q
      || d.file_name.toLowerCase().includes(q)
      || d.source_label.toLowerCase().includes(q)
      || (d.reference ?? "").toLowerCase().includes(q);
    const matchCat = category === "all" || d.category === category;
    return matchSearch && matchCat;
  });

  const openFile = async (item: UploadedDoc, preview: boolean) => {
    try {
      const { data } = await api.get<{ url: string; file_type: string }>(
        "/documents/uploaded/file-url",
        { params: { key: item.source_key, id: item.ref_id, inline: preview } },
      );
      const target = preview && data.file_type !== "pdf"
        ? `https://view.officeapps.live.com/op/view.aspx?src=${encodeURIComponent(data.url)}`
        : data.url;
      window.open(target, "_blank");
    } catch {
      setError("Could not open this file — it may no longer be available.");
    }
  };

  return (
    <div className="space-y-5">
      {/* header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900 uppercase tracking-wide">Uploaded Documents</h1>
          <p className="text-xs text-gray-500 mt-0.5">Every file uploaded to storage — statements, BSP, adjustments, vendor & customer statements, deals</p>
        </div>
        <button
          onClick={fetchDocs}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-2 border border-gray-200 rounded-lg text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
        </button>
      </div>

      {/* filter bar */}
      {!loading && !error && docs.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none" />
            <input
              type="text" placeholder="Search file, source or reference…"
              value={search} onChange={e => setSearch(e.target.value)}
              className="pl-8 pr-3 py-2 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 w-64"
            />
          </div>
          <select
            value={category} onChange={e => setCategory(e.target.value)}
            className="py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 text-gray-600 bg-white"
          >
            <option value="all">All Categories</option>
            {categories.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
          {(search || category !== "all") && (
            <button onClick={() => { setSearch(""); setCategory("all"); }} className="p-2 hover:bg-gray-100 rounded-lg text-gray-400" title="Clear filters">
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0" /> {error}
        </div>
      )}

      {loading && (
        <div className="flex items-center justify-center py-24">
          <div className="text-center space-y-3">
            <RefreshCw className="w-7 h-7 text-blue-400 animate-spin mx-auto" />
            <p className="text-sm text-gray-500">Loading documents…</p>
          </div>
        </div>
      )}

      {!loading && !error && docs.length === 0 && (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <div className="w-16 h-16 bg-gray-50 rounded-full flex items-center justify-center mb-4">
            <FolderOpen className="w-8 h-8 text-gray-300" />
          </div>
          <p className="text-sm font-medium text-gray-600">No uploaded documents yet</p>
          <p className="text-xs text-gray-400 mt-1">Files uploaded in Statements, BSP, Deals and other sections will appear here.</p>
        </div>
      )}

      {!loading && !error && docs.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="px-5 py-3 border-b border-gray-100 bg-gray-50/40 flex items-center justify-between">
            <p className="text-xs font-semibold text-gray-600 uppercase tracking-wider">
              {filtered.length === docs.length ? `${docs.length} Documents` : `${filtered.length} of ${docs.length} Documents`}
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr style={{ background: "#1e3a5f" }}>
                  <th className="px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide">File</th>
                  <th className="px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide">Source</th>
                  <th className="px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide">Category</th>
                  <th className="px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide">Reference</th>
                  <th className="px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide">Uploaded By</th>
                  <th className="px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide">Uploaded</th>
                  <th className="px-4 py-2 text-right text-[11px] font-semibold text-white/80 uppercase tracking-wide">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {filtered.length === 0 ? (
                  <tr><td colSpan={7} className="px-4 py-10 text-center text-xs text-gray-400">No documents match the current filters.</td></tr>
                ) : filtered.map(doc => (
                  <tr key={doc.id} className="hover:bg-blue-50/40 transition-colors">
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-2.5">
                        <div className="w-8 h-8 rounded-lg bg-gray-50 flex items-center justify-center shrink-0">
                          <FileIcon name={doc.file_name} />
                        </div>
                        <span className="text-sm font-medium text-gray-800 truncate max-w-55" title={doc.file_name}>{doc.file_name}</span>
                      </div>
                    </td>
                    <td className="px-4 py-2.5">
                      {doc.link ? (
                        <Link href={doc.link} className="inline-flex items-center gap-1 text-xs font-medium text-[#1e3a5f] hover:underline">
                          {doc.source_label} <ExternalLink className="w-3 h-3" />
                        </Link>
                      ) : (
                        <span className="text-xs font-medium text-gray-700">{doc.source_label}</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold ${CATEGORY_COLORS[doc.category] ?? "bg-gray-100 text-gray-600"}`}>
                        {doc.category}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-xs text-gray-600 truncate max-w-40" title={doc.reference ?? ""}>{doc.reference || "—"}</td>
                    <td className="px-4 py-2.5 text-xs text-gray-600 font-medium">{doc.uploaded_by || "—"}</td>
                    <td className="px-4 py-2.5 text-xs text-gray-500">{formatDate(doc.uploaded_at)}</td>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center justify-end gap-1">
                        <button onClick={() => openFile(doc, true)} title="Preview"
                          className="p-1.5 hover:bg-gray-100 rounded-lg text-gray-500 hover:text-[#1e3a5f]">
                          <Eye className="w-4 h-4" />
                        </button>
                        <button onClick={() => openFile(doc, false)} title="Download"
                          className="p-1.5 hover:bg-gray-100 rounded-lg text-gray-500 hover:text-[#1e3a5f]">
                          <Download className="w-4 h-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
