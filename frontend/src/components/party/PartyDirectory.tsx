"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle, ArrowRight, ChevronRight, Edit2, Plus,
  ReceiptIndianRupee, RefreshCw, Search, Trash2, Upload, X,
} from "lucide-react";
import api from "@/lib/api";
import Pagination from "@/components/ui/Pagination";
import PartyModal from "@/components/party/PartyModal";
import PartyUploadModal from "@/components/party/PartyUploadModal";
import { PARTY_ICON } from "@/components/party/icons";
import {
  PARTY, billingTypeLabel, corporateTypeLabel, markupTypeLabel, markupValueLabel, partyName,
  type Party, type PartyKind, type PartyMode,
} from "@/lib/party";

const PAGE_SIZE = 25;

// The first three columns are what a customer and a corporate disagree about: a
// customer is a person at a company, a corporate is an organisation of some legal
// form, somewhere. The rest — contact, tax ids, markup, billing — is shared.
const LEAD_COLUMNS: Record<PartyKind, string[]> = {
  customer: ["NAME", "CORPORATE", "TITLE"],
  corporate: ["CORPORATE NAME", "TYPE", "CITY"],
};
const TAIL_COLUMNS = ["EMAIL", "PHONE", "GST NO", "PAN NO", "MARKUP TYPE", "MARKUP VALUE", "BILLING"];

/**
 * The customer / corporate list, in one of two modes:
 *
 *   master  — User master. Add, import, edit and delete the parties you work
 *             with; each row offers "Bill" as the way through to Billing.
 *   billing — Billing. A picker: search, click a row, bill it. Deliberately
 *             has no write actions — those live in the master.
 */
export default function PartyDirectory({ kind, mode }: { kind: PartyKind; mode: PartyMode }) {
  const cfg = PARTY[kind];
  const Icon = PARTY_ICON[kind];
  const isMaster = mode === "master";
  const isCorporate = kind === "corporate";
  const columns = useMemo(() => [...LEAD_COLUMNS[kind], ...TAIL_COLUMNS], [kind]);
  // User master calls a customer an Employee; Billing calls them a Customer.
  // Same rows, two contexts — see PartyConfig in lib/party.ts.
  const one = isMaster ? cfg.masterSingular : cfg.singular;
  const many = isMaster ? cfg.masterPlural : cfg.plural;
  const router = useRouter();

  const [parties, setParties] = useState<Party[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [showAdd, setShowAdd] = useState(false);
  const [showUpload, setShowUpload] = useState(false);
  const [editTarget, setEditTarget] = useState<Party | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Party | null>(null);
  const [deleting, setDeleting] = useState(false);

  const fetchParties = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get<Party[]>(`/${cfg.resource}/`, { params: { limit: 500 } });
      setParties(data);
    } catch {
      setError(`Failed to load ${many.toLowerCase()}.`);
    } finally {
      setLoading(false);
    }
  }, [cfg.resource, many]);

  useEffect(() => {
    fetchParties();
  }, [fetchParties]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return parties;
    return parties.filter((p) =>
      [p.first_name, p.last_name, p.company, p.email, p.phone, p.city, p.state]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q))
    );
  }, [parties, search]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const pageItems = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  useEffect(() => {
    if (page > totalPages) setPage(1);
  }, [page, totalPages]);

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.delete(`/${cfg.resource}/${deleteTarget.id}`);
      setDeleteTarget(null);
      fetchParties();
    } catch {
      alert(`Failed to delete ${one.toLowerCase()}.`);
    } finally {
      setDeleting(false);
    }
  };

  const colCount = columns.length + (isMaster ? 1 : 0);

  const crossLink = isMaster
    ? { href: cfg.billingHref, label: cfg.billingLabel }
    : { href: cfg.masterHref, label: cfg.masterLabel };

  return (
    <div className="space-y-4">
      {/* In master mode the User Master layout supplies the heading, so only the
          action row is rendered here. Billing owns its own page header. */}
      <div className="flex items-start justify-between">
        {isMaster ? (
          <p className="text-xs text-gray-500 self-center">
            {parties.length} {parties.length === 1 ? one.toLowerCase() : many.toLowerCase()}
          </p>
        ) : (
          <div>
            <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">Billing</p>
            <h1 className="text-xl font-bold text-gray-900">{cfg.billingLabel}</h1>
            <p className="text-xs text-gray-500 mt-0.5">
              Pick a {cfg.singular.toLowerCase()} to bill. Add or edit {cfg.masterPlural.toLowerCase()} in {cfg.masterLabel}.
            </p>
          </div>
        )}

        <div className="flex gap-2">
          <Link
            href={crossLink.href}
            className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-600 px-3.5 py-2 rounded-lg text-xs font-semibold hover:bg-gray-50"
          >
            {crossLink.label} <ArrowRight className="w-3.5 h-3.5" />
          </Link>
          <button
            onClick={fetchParties}
            disabled={loading}
            className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-600 px-3 py-2 rounded-lg text-xs font-medium hover:bg-gray-50 disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          </button>
          {isMaster && (
            <>
              <button
                onClick={() => setShowUpload(true)}
                className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-700 px-3.5 py-2 rounded-lg text-xs font-semibold hover:bg-gray-50"
              >
                <Upload className="w-3.5 h-3.5" /> Upload Excel
              </button>
              <button
                onClick={() => setShowAdd(true)}
                className="flex items-center gap-1.5 bg-[#1e3a5f] hover:bg-[#16304f] text-white text-xs font-semibold px-3.5 py-2 rounded-lg shadow-sm"
              >
                <Plus className="w-3.5 h-3.5" /> Add {one}
              </button>
            </>
          )}
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100 flex-wrap">
          <div className="relative flex-1 min-w-48">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
            <input
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
              placeholder={
                isCorporate
                  ? "Search by name, city, email or phone…"
                  : "Search by name, company, email or phone…"
              }
              className="w-full pl-8 pr-3 py-1.5 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-[#1e3a5f]/40 bg-gray-50"
            />
          </div>
          <span className="text-[11px] text-gray-400 ml-auto">{filtered.length} shown</span>
        </div>

        {error && <div className="px-4 py-3 text-xs text-red-500 bg-red-50 border-b border-red-100">{error}</div>}

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr style={{ background: "#1e3a5f" }}>
                {[...columns, ...(isMaster ? ["ACTIONS"] : [])].map((h) => (
                  <th key={h} className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={colCount} className="px-4 py-12 text-center text-xs text-gray-400">
                    <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" /> Loading {many.toLowerCase()}…
                  </td>
                </tr>
              ) : pageItems.length === 0 ? (
                <tr>
                  <td colSpan={colCount} className="px-4 py-16 text-center">
                    <div className="flex flex-col items-center justify-center text-center">
                      <div className="w-14 h-14 bg-gray-50 rounded-full flex items-center justify-center mb-3">
                        <Icon className="w-7 h-7 text-gray-300" />
                      </div>
                      <p className="text-sm font-medium text-gray-600">No {many.toLowerCase()} yet</p>
                      {isMaster ? (
                        <>
                          <p className="text-xs text-gray-400 mt-1 mb-4">
                            Add a {one.toLowerCase()} manually or import from Excel.
                          </p>
                          <div className="flex gap-2">
                            <button onClick={() => setShowAdd(true)} className="flex items-center gap-1.5 bg-[#1e3a5f] hover:bg-[#16304f] text-white text-xs font-semibold px-3.5 py-2 rounded-lg">
                              <Plus className="w-3.5 h-3.5" /> Add {one}
                            </button>
                            <button onClick={() => setShowUpload(true)} className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-700 text-xs font-semibold px-3.5 py-2 rounded-lg hover:bg-gray-50">
                              <Upload className="w-3.5 h-3.5" /> Upload Excel
                            </button>
                          </div>
                        </>
                      ) : (
                        <>
                          <p className="text-xs text-gray-400 mt-1 mb-4">
                            {cfg.masterPlural} are added in {cfg.masterLabel}.
                          </p>
                          <Link href={cfg.masterHref} className="flex items-center gap-1.5 bg-[#1e3a5f] hover:bg-[#16304f] text-white text-xs font-semibold px-3.5 py-2 rounded-lg">
                            Go to {cfg.masterLabel} <ArrowRight className="w-3.5 h-3.5" />
                          </Link>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ) : (
                pageItems.map((p, idx) => (
                  <tr
                    key={p.id}
                    onClick={() => (isMaster ? setEditTarget(p) : router.push(cfg.detailHref(p.id)))}
                    className={`border-b border-gray-50 hover:bg-blue-50/40 transition-colors group cursor-pointer ${idx % 2 === 0 ? "bg-white" : "bg-gray-50/30"}`}
                  >
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-1.5">
                        <span className="font-semibold text-[12px] text-gray-800">{partyName(p)}</span>
                        {!isMaster && <ChevronRight className="w-3 h-3 text-gray-300 group-hover:text-[#1e3a5f]" />}
                      </div>
                    </td>
                    {isCorporate ? (
                      <>
                        <td className="px-3 py-2 text-[11px] text-gray-600">{corporateTypeLabel(p.corporate_type)}</td>
                        <td className="px-3 py-2 text-[11px] text-gray-500">{p.city ?? "—"}</td>
                      </>
                    ) : (
                      <>
                        <td className="px-3 py-2 text-[11px] text-gray-600">
                          {p.company ? (
                            p.company
                          ) : (
                            // No employer is a real answer here, not missing data.
                            <span className="text-gray-400">Individual / Direct</span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-[11px] text-gray-500">{p.title ?? "—"}</td>
                      </>
                    )}
                    <td className="px-3 py-2 text-[11px] text-gray-500">{p.email ?? "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-500">{p.phone ?? "—"}</td>
                    <td className="px-3 py-2 text-[11px] font-mono text-gray-600">
                      {p.gst_registered ? (p.gst_no ?? "—") : <span className="text-gray-400">Unregistered</span>}
                    </td>
                    <td className="px-3 py-2 text-[11px] font-mono text-gray-600">{p.pan_no ?? "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{markupTypeLabel(p)}</td>
                    <td className="px-3 py-2 text-[11px] font-semibold text-gray-700">{markupValueLabel(p)}</td>
                    <td className="px-3 py-2">
                      {p.billing_type ? (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-blue-50 text-blue-700 border border-blue-100">
                          {billingTypeLabel(p)}
                        </span>
                      ) : (
                        <span className="text-[11px] text-gray-400">—</span>
                      )}
                    </td>
                    {isMaster && (
                      <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => router.push(cfg.detailHref(p.id))}
                            className="p-1.5 hover:bg-green-50 rounded-lg"
                            title={`Bill this ${cfg.singular.toLowerCase()}`}
                          >
                            <ReceiptIndianRupee className="w-3.5 h-3.5 text-green-600" />
                          </button>
                          <button onClick={() => setEditTarget(p)} className="p-1.5 hover:bg-blue-50 rounded-lg" title="Edit">
                            <Edit2 className="w-3.5 h-3.5 text-blue-500" />
                          </button>
                          <button onClick={() => setDeleteTarget(p)} className="p-1.5 hover:bg-red-50 rounded-lg" title="Delete">
                            <Trash2 className="w-3.5 h-3.5 text-red-400" />
                          </button>
                        </div>
                      </td>
                    )}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        {filtered.length > PAGE_SIZE && (
          <Pagination page={page} pageSize={PAGE_SIZE} total={filtered.length} onPageChange={(p) => setPage(p)} />
        )}
      </div>

      {showAdd && <PartyModal kind={kind} onClose={() => setShowAdd(false)} onSaved={fetchParties} />}
      {showUpload && <PartyUploadModal kind={kind} onClose={() => setShowUpload(false)} onSaved={fetchParties} />}
      {editTarget && <PartyModal kind={kind} party={editTarget} onClose={() => setEditTarget(null)} onSaved={fetchParties} />}

      {deleteTarget && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-red-50 flex items-center justify-center">
                  <AlertTriangle className="w-4 h-4 text-red-500" />
                </div>
                <h2 className="text-sm font-bold text-gray-900">Delete {one}</h2>
              </div>
              <button onClick={() => setDeleteTarget(null)} className="p-1.5 hover:bg-gray-100 rounded-lg">
                <X className="w-4 h-4 text-gray-500" />
              </button>
            </div>
            <div className="px-6 py-4">
              <p className="text-sm text-gray-600">
                Are you sure you want to delete{" "}
                <span className="font-semibold text-gray-900">{partyName(deleteTarget)}</span>? This action cannot be
                undone, and any saved billings for this {one.toLowerCase()} will be deleted with it.
              </p>
            </div>
            <div className="px-6 pb-5 flex gap-3">
              <button
                onClick={() => setDeleteTarget(null)}
                className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={confirmDelete}
                disabled={deleting}
                className="flex-1 bg-red-500 hover:bg-red-600 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50"
              >
                {deleting ? "Deleting…" : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
