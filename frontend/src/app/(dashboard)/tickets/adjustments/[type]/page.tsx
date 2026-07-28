"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { Plus, Edit2, Trash2, RefreshCw, X, AlertTriangle } from "lucide-react";
import api from "@/lib/api";
import toast from "react-hot-toast";
import AdjustmentRepository from "@/components/adjustments/AdjustmentRepository";

// ADM/ACM/RA are IATA export uploads (XLS/CSV → per-type tables + repository).
// The remaining slugs (refund/debit/credit) stay on the manual-entry CRUD below.
const UPLOAD_SLUGS = new Set(["adm", "acm", "ra"]);

// ── slug (URL) ↔ adjustment type + display metadata ─────────────────────────
const SLUG_MAP: Record<string, { type: string; title: string; blurb: string }> = {
  "adm":          { type: "ADM",        title: "ADM",          blurb: "Agency Debit Memo — the airline says the agency owes money." },
  "acm":          { type: "ACM",        title: "ACM",          blurb: "Agency Credit Memo — the airline owes the agency money." },
  "refund":       { type: "Refund",     title: "Refund",       blurb: "Money returned after a cancellation." },
  "ra":           { type: "RA",         title: "RA",           blurb: "Refund Application submitted for a ticket refund." },
  "debit-notes":  { type: "DebitNote",  title: "Debit Notes",  blurb: "Manually recorded debit notes against a ticket." },
  "credit-notes": { type: "CreditNote", title: "Credit Notes", blurb: "Manually recorded credit notes against a ticket." },
};

const STATUSES = ["open", "settled", "disputed", "void"] as const;

type Adjustment = {
  id: number;
  ticket_id: number | null;
  ticket_number: string | null;
  type: string;
  reference_no: string | null;
  amount: number;
  reason: string | null;
  adjustment_date: string | null;
  remarks: string | null;
  status: string;
  source: string;
  created_at: string;
  updated_at: string;
};

type FormState = {
  ticket_number: string;
  reference_no: string;
  amount: string;
  adjustment_date: string;
  status: string;
  reason: string;
  remarks: string;
};

const EMPTY_FORM: FormState = {
  ticket_number: "", reference_no: "", amount: "", adjustment_date: "", status: "open", reason: "", remarks: "",
};

function statusBadge(s: string): string {
  switch (s) {
    case "settled":  return "bg-emerald-50 text-emerald-700 border-emerald-200";
    case "disputed": return "bg-red-50 text-red-700 border-red-200";
    case "void":     return "bg-gray-100 text-gray-500 border-gray-200";
    default:         return "bg-amber-50 text-amber-700 border-amber-200"; // open
  }
}

export default function AdjustmentsPage() {
  const params = useParams<{ type: string }>();
  const slug = (params?.type as string) || "adm";
  const meta = SLUG_MAP[slug] ?? { type: slug, title: slug, blurb: "" };

  // ADM/ACM/RA use the XLS-upload repository; the rest use the manual CRUD form.
  if (UPLOAD_SLUGS.has(slug)) {
    return <AdjustmentRepository slug={slug} title={meta.title} blurb={meta.blurb} />;
  }
  return <ManualAdjustmentsPage meta={meta} />;
}

function ManualAdjustmentsPage({ meta }: { meta: { type: string; title: string; blurb: string } }) {
  const adjType = meta.type;

  const [rows, setRows] = useState<Adjustment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [modalOpen, setModalOpen] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Adjustment | null>(null);
  const [deleting, setDeleting] = useState(false);

  const fetchRows = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get<Adjustment[]>("/adjustments/", { params: { type: adjType } });
      setRows(data);
    } catch {
      setError("Failed to load adjustments.");
    } finally {
      setLoading(false);
    }
  }, [adjType]);

  useEffect(() => { fetchRows(); }, [fetchRows]);

  const total = useMemo(() => rows.reduce((s, r) => s + (Number(r.amount) || 0), 0), [rows]);

  const openCreate = () => { setEditId(null); setForm(EMPTY_FORM); setModalOpen(true); };
  const openEdit = (r: Adjustment) => {
    setEditId(r.id);
    setForm({
      ticket_number: r.ticket_number ?? "",
      reference_no: r.reference_no ?? "",
      amount: r.amount != null ? String(r.amount) : "",
      adjustment_date: r.adjustment_date ?? "",
      status: r.status ?? "open",
      reason: r.reason ?? "",
      remarks: r.remarks ?? "",
    });
    setModalOpen(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      const body = {
        type: adjType,
        ticket_number: form.ticket_number.trim() || null,
        reference_no: form.reference_no.trim() || null,
        amount: form.amount === "" ? 0 : Number(form.amount),
        adjustment_date: form.adjustment_date || null,
        status: form.status,
        reason: form.reason.trim() || null,
        remarks: form.remarks.trim() || null,
      };
      if (editId != null) {
        await api.patch(`/adjustments/${editId}`, body);
        toast.success("Adjustment updated.");
      } else {
        await api.post("/adjustments/", body);
        toast.success(`${meta.title} added.`);
      }
      setModalOpen(false);
      await fetchRows();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(typeof msg === "string" ? msg : "Failed to save adjustment.");
    } finally {
      setSaving(false);
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.delete(`/adjustments/${deleteTarget.id}`);
      toast.success("Adjustment deleted.");
      setDeleteTarget(null);
      await fetchRows();
    } catch {
      toast.error("Failed to delete adjustment.");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="w-full pb-16">
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div>
          <h1 className="text-xl font-bold text-gray-900">{meta.title}</h1>
          {meta.blurb && <p className="text-xs text-gray-400 mt-0.5">{meta.blurb}</p>}
        </div>
        <div className="flex items-center gap-2">
          <button onClick={fetchRows} className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-500 border border-gray-200 rounded-lg hover:bg-gray-50">
            <RefreshCw className="w-3.5 h-3.5" /> Refresh
          </button>
          <button onClick={openCreate} className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700">
            <Plus className="w-3.5 h-3.5" /> New {meta.title}
          </button>
        </div>
      </div>

      {/* Summary strip */}
      <div className="flex gap-3 mb-4">
        <div className="bg-white border border-gray-200 rounded-lg px-4 py-2.5">
          <p className="text-[10px] uppercase tracking-wide text-gray-400">Count</p>
          <p className="text-lg font-bold text-gray-800">{rows.length}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg px-4 py-2.5">
          <p className="text-[10px] uppercase tracking-wide text-gray-400">Total amount</p>
          <p className="text-lg font-bold text-gray-800">₹{total.toLocaleString("en-IN", { maximumFractionDigits: 2 })}</p>
        </div>
      </div>

      {/* Table */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200 text-[11px] uppercase tracking-wide text-gray-400">
                <th className="px-3 py-2.5 font-semibold">Ticket #</th>
                <th className="px-3 py-2.5 font-semibold">Reference</th>
                <th className="px-3 py-2.5 font-semibold text-right">Amount</th>
                <th className="px-3 py-2.5 font-semibold">Date</th>
                <th className="px-3 py-2.5 font-semibold">Status</th>
                <th className="px-3 py-2.5 font-semibold">Source</th>
                <th className="px-3 py-2.5 font-semibold">Reason</th>
                <th className="px-3 py-2.5 font-semibold text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={8} className="px-3 py-10 text-center text-sm text-gray-400">Loading…</td></tr>
              ) : error ? (
                <tr><td colSpan={8} className="px-3 py-10 text-center text-sm text-red-500">{error}</td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={8} className="px-3 py-10 text-center text-sm text-gray-400">No {meta.title} recorded yet.</td></tr>
              ) : rows.map(r => (
                <tr key={r.id} className="border-b border-gray-100 hover:bg-gray-50/60">
                  <td className="px-3 py-2.5 text-xs text-gray-800">
                    {r.ticket_number || "—"}
                    {r.ticket_number && r.ticket_id == null && (
                      <span className="ml-1.5 text-[10px] text-amber-600" title="No matching ticket found">⚠ unmatched</span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-xs text-gray-600">{r.reference_no || "—"}</td>
                  <td className="px-3 py-2.5 text-xs text-gray-800 text-right">₹{Number(r.amount).toLocaleString("en-IN", { maximumFractionDigits: 2 })}</td>
                  <td className="px-3 py-2.5 text-xs text-gray-600">{r.adjustment_date || "—"}</td>
                  <td className="px-3 py-2.5">
                    <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border capitalize ${statusBadge(r.status)}`}>{r.status}</span>
                  </td>
                  <td className="px-3 py-2.5 text-xs text-gray-500 capitalize">{r.source}</td>
                  <td className="px-3 py-2.5 text-xs text-gray-600 max-w-[220px] truncate" title={r.reason ?? undefined}>{r.reason || "—"}</td>
                  <td className="px-3 py-2.5 text-right whitespace-nowrap">
                    <button onClick={() => openEdit(r)} className="p-1.5 text-gray-400 hover:text-blue-600" title="Edit"><Edit2 className="w-3.5 h-3.5" /></button>
                    <button onClick={() => setDeleteTarget(r)} className="p-1.5 text-gray-400 hover:text-red-600" title="Delete"><Trash2 className="w-3.5 h-3.5" /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Create / Edit modal */}
      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-lg">
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-gray-100">
              <h2 className="text-sm font-semibold text-gray-800">{editId != null ? `Edit ${meta.title}` : `New ${meta.title}`}</h2>
              <button onClick={() => setModalOpen(false)} className="text-gray-400 hover:text-gray-600"><X className="w-4 h-4" /></button>
            </div>
            <div className="px-5 py-4 grid grid-cols-2 gap-3">
              <Field label="Ticket Number">
                <input value={form.ticket_number} onChange={e => setForm({ ...form, ticket_number: e.target.value })}
                  className="w-full border border-gray-200 rounded-md px-2.5 py-1.5 text-xs" placeholder="e.g. 0571234567890" />
              </Field>
              <Field label="Reference No.">
                <input value={form.reference_no} onChange={e => setForm({ ...form, reference_no: e.target.value })}
                  className="w-full border border-gray-200 rounded-md px-2.5 py-1.5 text-xs" placeholder="ADM/ACM document no." />
              </Field>
              <Field label="Amount">
                <input type="number" value={form.amount} onChange={e => setForm({ ...form, amount: e.target.value })}
                  className="w-full border border-gray-200 rounded-md px-2.5 py-1.5 text-xs" placeholder="0.00" />
              </Field>
              <Field label="Adjustment Date">
                <input type="date" value={form.adjustment_date} onChange={e => setForm({ ...form, adjustment_date: e.target.value })}
                  className="w-full border border-gray-200 rounded-md px-2.5 py-1.5 text-xs" />
              </Field>
              <Field label="Status">
                <select value={form.status} onChange={e => setForm({ ...form, status: e.target.value })}
                  className="w-full border border-gray-200 rounded-md px-2.5 py-1.5 text-xs bg-white capitalize">
                  {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </Field>
              <Field label="Reason" full>
                <input value={form.reason} onChange={e => setForm({ ...form, reason: e.target.value })}
                  className="w-full border border-gray-200 rounded-md px-2.5 py-1.5 text-xs" placeholder="e.g. incorrect fare / commission claw-back" />
              </Field>
              <Field label="Remarks" full>
                <textarea value={form.remarks} onChange={e => setForm({ ...form, remarks: e.target.value })} rows={2}
                  className="w-full border border-gray-200 rounded-md px-2.5 py-1.5 text-xs resize-none" />
              </Field>
            </div>
            <div className="flex justify-end gap-2 px-5 py-3.5 border-t border-gray-100">
              <button onClick={() => setModalOpen(false)} className="px-3 py-1.5 text-xs font-medium text-gray-500 border border-gray-200 rounded-lg hover:bg-gray-50">Cancel</button>
              <button onClick={save} disabled={saving} className="px-4 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50">
                {saving ? "Saving…" : editId != null ? "Save changes" : "Add"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete confirm */}
      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-5">
            <div className="flex items-center gap-2.5 mb-2">
              <AlertTriangle className="w-5 h-5 text-red-500" />
              <h2 className="text-sm font-semibold text-gray-800">Delete {meta.title}?</h2>
            </div>
            <p className="text-xs text-gray-500 mb-4">
              This permanently removes the {meta.title} record{deleteTarget.reference_no ? ` (${deleteTarget.reference_no})` : ""}. This cannot be undone.
            </p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setDeleteTarget(null)} className="px-3 py-1.5 text-xs font-medium text-gray-500 border border-gray-200 rounded-lg hover:bg-gray-50">Cancel</button>
              <button onClick={confirmDelete} disabled={deleting} className="px-4 py-1.5 text-xs font-semibold text-white bg-red-600 rounded-lg hover:bg-red-700 disabled:opacity-50">
                {deleting ? "Deleting…" : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, children, full }: { label: string; children: React.ReactNode; full?: boolean }) {
  return (
    <div className={full ? "col-span-2" : ""}>
      <label className="block text-[11px] font-medium text-gray-500 mb-1 uppercase tracking-wide">{label}</label>
      {children}
    </div>
  );
}
