"use client";

// IATA Commission — one master, two doors.
//
//   Master Governance → IATA Commission   (platform admin)
//     The master list itself: add / edit / delete / export, plus the queue of
//     pending requests to approve, edit or reject.
//
//   System master update → IATA Commission (tenant user)
//     Submit a new row or an update to an existing one, and watch what happens
//     to it. Exactly the flow Suppliers / Airlines / Airports / Classes use —
//     the per-airline commission percentages are one global master, so a tenant
//     proposes changes rather than keeping its own copy.

import { useState, useEffect, useCallback } from "react";
import {
  Edit2, Trash2, RefreshCw, Plus, Search, X, Check,
  Percent, TrendingUp, Upload, CheckCircle, XCircle, Clock,
} from "lucide-react";
import api from "@/lib/api";
import { canManageGlobalMasters, canSubmitMasterRequest, canViewMasterRequests } from "@/lib/rbac";
import { useAppSelector } from "@/store/hooks";
import ExportMasterButton from "@/components/masters/ExportMasterButton";
import MasterDiffModal, { DiffFieldSpec } from "@/components/masters/MasterDiffModal";
import {
  type IataCommissionRow, INPUT, LABEL, apiError,
  ActiveBadge, UploadBox, ModalShell,
} from "@/components/userMaster/shared";

type AirlineOpt = { id: number; name: string; iata_code: string; icao_code: string | null };

type Approval = {
  id: number;
  airline_name: string;
  airline_code: string | null;
  iata_numeric_code: string | null;
  iata_commission_pct: number | null;
  valid_from: string | null;
  valid_to: string | null;
  status: "pending" | "approved" | "rejected";
  submitted_by: { id: number; full_name: string; email: string };
  submitted_at: string;
  reviewed_at: string | null;
  rejection_reason: string | null;
  request_type: "new" | "update";
  target_id: number | null;
  // ── platform-admin edit state ────────────────────────────────────────────
  /** True only when an admin changed something the submitter should see. */
  edited?: boolean;
  /** The business values as the submitter originally sent them. */
  original_payload?: Record<string, unknown> | null;
  edited_by?: { id: number; full_name: string; email: string } | null;
  edited_at?: string | null;
};

const READONLY_INPUT =
  "w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-gray-100 text-gray-500 cursor-not-allowed focus:outline-none";

const fmtPct = (v: unknown) =>
  v == null || v === "" ? "—" : `${Number(v).toLocaleString("en-IN")}%`;
const fmtDate = (v: unknown) => (v ? String(v).slice(0, 10) : "—");

const DIFF_FIELDS: DiffFieldSpec[] = [
  { key: "airline_name",        label: "Airline" },
  { key: "airline_code",        label: "Airline Code" },
  { key: "iata_numeric_code",   label: "IATA Numeric Code" },
  // The API sends a number, the snapshot a number too — compare numerically so
  // 5 and 5.00 do not read as a change.
  {
    key: "iata_commission_pct", label: "IATA Commission %",
    render: (v) => (v == null || v === "" ? <span className="text-gray-300">—</span> : fmtPct(v)),
    equals: (a, b) =>
      (a == null || a === "") && (b == null || b === "")
        ? true
        : Number(a) === Number(b),
  },
  { key: "valid_from", label: "Valid From", render: (v) => (v ? fmtDate(v) : <span className="text-gray-300">—</span>) },
  { key: "valid_to",   label: "Valid To",   render: (v) => (v ? fmtDate(v) : <span className="text-gray-300">—</span>) },
];

// The form is one shape for both the "submit a request" and "edit a request"
// modals — only where it is POSTed differs.
const emptyForm = {
  airline_name: "",
  airline_code: "",
  iata_numeric_code: "",
  iata_commission_pct: "",
  valid_from: "",
  valid_to: "",
};
type FormState = typeof emptyForm;

/** The airline picker + the three read-only/typed fields every form shares. */
function CommissionFields({
  form, setForm, airlines, disabled,
}: {
  form: FormState;
  setForm: (fn: (p: FormState) => FormState) => void;
  airlines: AirlineOpt[];
  disabled?: boolean;
}) {
  const set = (k: keyof FormState, v: string) => setForm(p => ({ ...p, [k]: v }));

  return (
    <>
      <div>
        <label className={LABEL}>Airline *</label>
        <select
          value={form.airline_name}
          disabled={disabled}
          onChange={e => {
            const name = e.target.value;
            const a = airlines.find(x => x.name === name);
            setForm(p => ({
              ...p,
              airline_name: name,
              airline_code: a ? a.iata_code : "",
              iata_numeric_code: a?.icao_code ?? "",
            }));
          }}
          className={INPUT}
        >
          <option value="">— Select airline —</option>
          {/* An airline that has since been renamed or removed from the master
              would otherwise vanish from the row being edited. */}
          {form.airline_name && !airlines.some(a => a.name === form.airline_name) && (
            <option value={form.airline_name}>{form.airline_name}</option>
          )}
          {airlines.map(a => <option key={a.id} value={a.name}>{a.name}</option>)}
        </select>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL}>Airline Code</label>
          <input value={form.airline_code} readOnly placeholder="Auto-filled"
            title="Auto-filled from the selected airline" className={READONLY_INPUT} />
        </div>
        <div>
          <label className={LABEL}>IATA Numeric Code</label>
          <input value={form.iata_numeric_code} readOnly placeholder="Auto-filled"
            title="Auto-filled from the selected airline" className={READONLY_INPUT} />
        </div>
      </div>

      <div>
        <label className={LABEL}>IATA Commission %</label>
        <input type="number" step="any" value={form.iata_commission_pct}
          onChange={e => set("iata_commission_pct", e.target.value)}
          placeholder="e.g. 5" className={INPUT} />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL}>Valid From</label>
          <input type="date" value={form.valid_from} onChange={e => set("valid_from", e.target.value)} className={INPUT} />
        </div>
        <div>
          <label className={LABEL}>Valid To</label>
          <input type="date" value={form.valid_to} onChange={e => set("valid_to", e.target.value)} className={INPUT} />
        </div>
      </div>
    </>
  );
}

/** The business half of the payload, shared by create and admin-edit. */
const formBody = (form: FormState) => ({
  airline_name: form.airline_name.trim(),
  airline_code: form.airline_code.trim() || null,
  iata_numeric_code: form.iata_numeric_code.trim() || null,
  iata_commission_pct:
    form.iata_commission_pct.trim() === "" ? null : Number(form.iata_commission_pct),
  valid_from: form.valid_from || null,
  valid_to: form.valid_to || null,
});

// ── submit / add ───────────────────────────────────────────────────────────

function AddCommissionModal({
  airlines, isPlatformAdmin, onClose, onSaved,
}: {
  airlines: AirlineOpt[];
  isPlatformAdmin: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [tab, setTab] = useState<"manual" | "xls">("manual");
  const [requestType, setRequestType] = useState<"new" | "update">("new");
  const [targetId, setTargetId] = useState<number | null>(null);
  const [existing, setExisting] = useState<IataCommissionRow[]>([]);
  const [form, setForm] = useState<FormState>({ ...emptyForm });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (requestType === "update" && existing.length === 0) {
      api.get<IataCommissionRow[]>("/iata-commissions/", { params: { limit: 1000 } })
        .then(r => setExisting(r.data))
        .catch(() => {});
    }
  }, [requestType, existing.length]);

  const handleTargetSelect = (id: number) => {
    setTargetId(id);
    const row = existing.find(r => r.id === id);
    if (row) {
      setForm({
        airline_name: row.airline_name,
        airline_code: row.airline_code ?? "",
        iata_numeric_code: row.iata_numeric_code ?? "",
        iata_commission_pct: row.iata_commission_pct != null ? String(row.iata_commission_pct) : "",
        valid_from: row.valid_from?.slice(0, 10) ?? "",
        valid_to: row.valid_to?.slice(0, 10) ?? "",
      });
    }
  };

  const save = async () => {
    if (!form.airline_name.trim()) { setError("Airline is required."); return; }
    if (requestType === "update" && !targetId) {
      setError("Please select the IATA commission row you want to update."); return;
    }
    setSaving(true); setError("");
    try {
      await api.post("/iata-commissions/", {
        ...formBody(form),
        request_type: requestType,
        target_id: targetId,
      });
      onSaved();
      onClose();
    } catch (e) { setError(apiError(e)); }
    finally { setSaving(false); }
  };

  const title = requestType === "update" ? "Update IATA Commission" : "Add IATA Commission";

  return (
    <ModalShell title={title} onClose={onClose}>
      <p className="text-[10px] text-gray-400 -mt-2 mb-3">
        {isPlatformAdmin
          ? requestType === "update"
            ? "Will directly update the existing record"
            : "Will be added directly to master data"
          : requestType === "update"
            ? "Update request will be sent for approval"
            : "Will be sent for Platform Admin approval"}
      </p>

      <div className="flex border-b border-gray-100 mb-4">
        {(["manual", "xls"] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`flex-1 py-2.5 text-xs font-semibold ${
              tab === t ? "border-b-2 border-sky-500 text-sky-600" : "text-gray-400 hover:text-gray-600"
            }`}>
            {t === "manual" ? "Manual Entry" : "Upload XLS"}
          </button>
        ))}
      </div>

      {tab === "manual" ? (
        <div className="space-y-3">
          {/* New / Update toggle */}
          <div className="flex gap-2">
            {(["new", "update"] as const).map(rt => (
              <button
                key={rt}
                type="button"
                onClick={() => { setRequestType(rt); setTargetId(null); setForm({ ...emptyForm }); }}
                className={`flex-1 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${
                  requestType === rt
                    ? rt === "new"
                      ? "bg-sky-600 text-white border-sky-600"
                      : "bg-amber-500 text-white border-amber-500"
                    : "bg-white text-gray-500 border-gray-200 hover:border-gray-300"
                }`}
              >
                {rt === "new" ? "New Entry" : "Update Existing"}
              </button>
            ))}
          </div>

          {requestType === "update" && (
            <div>
              <label className={LABEL}>Select Row to Update *</label>
              <select
                value={targetId ?? ""}
                onChange={e => handleTargetSelect(Number(e.target.value))}
                className="w-full border border-amber-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400 bg-amber-50"
              >
                <option value="">— choose existing row —</option>
                {existing.map(r => (
                  <option key={r.id} value={r.id}>
                    {r.airline_name}
                    {r.airline_code ? ` (${r.airline_code})` : ""}
                    {" — "}{fmtPct(r.iata_commission_pct)}
                    {r.valid_from ? ` from ${fmtDate(r.valid_from)}` : ""}
                  </option>
                ))}
              </select>
            </div>
          )}

          <CommissionFields form={form} setForm={setForm} airlines={airlines} />

          {error && <p className="text-[11px] text-red-500">{error}</p>}

          <div className="flex gap-3 pt-1">
            <button onClick={onClose}
              className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">
              Cancel
            </button>
            <button onClick={save} disabled={saving}
              className="flex-1 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50"
              style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
              {saving
                ? "Saving…"
                : requestType === "update"
                  ? isPlatformAdmin ? "Update Row" : "Submit Update for Approval"
                  : isPlatformAdmin ? "Create IATA Commission" : "Submit for Approval"}
            </button>
          </div>
        </div>
      ) : (
        <UploadBox resource="iata-commissions" templateName="iata_commission_template.xlsx"
          columns="AIRLINE_NAME, AIRLINE_CODE, IATA_NUMERIC_CODE, IATA_COMMISSION_PCT, VALID_FROM, VALID_TO, ACTIVE"
          onDone={onSaved} />
      )}
    </ModalShell>
  );
}

// ── platform admin edits a master row ──────────────────────────────────────

function EditCommissionModal({
  row, airlines, onClose, onSaved,
}: {
  row: IataCommissionRow;
  airlines: AirlineOpt[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<FormState>({
    airline_name: row.airline_name,
    airline_code: row.airline_code ?? "",
    iata_numeric_code: row.iata_numeric_code ?? "",
    iata_commission_pct: row.iata_commission_pct != null ? String(row.iata_commission_pct) : "",
    valid_from: row.valid_from?.slice(0, 10) ?? "",
    valid_to: row.valid_to?.slice(0, 10) ?? "",
  });
  const [isActive, setIsActive] = useState(row.is_active);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const save = async () => {
    if (!form.airline_name.trim()) { setError("Airline is required."); return; }
    setSaving(true); setError("");
    try {
      await api.patch(`/iata-commissions/${row.id}`, { ...formBody(form), is_active: isActive });
      onSaved();
      onClose();
    } catch (e) { setError(apiError(e)); }
    finally { setSaving(false); }
  };

  return (
    <ModalShell title="Edit IATA Commission" onClose={onClose}>
      <div className="space-y-3">
        <CommissionFields form={form} setForm={setForm} airlines={airlines} />

        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={isActive} onChange={e => setIsActive(e.target.checked)}
            className="w-4 h-4 rounded border-gray-300 text-sky-600 focus:ring-sky-400" />
          <span className="text-xs font-semibold text-gray-600">Active</span>
        </label>

        {error && <p className="text-[11px] text-red-500">{error}</p>}

        <div className="flex gap-3 pt-1">
          <button onClick={onClose}
            className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
          <button onClick={save} disabled={saving}
            className="flex-1 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50"
            style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
            {saving ? "Saving…" : "Save Changes"}
          </button>
        </div>
      </div>
    </ModalShell>
  );
}

// ── platform admin edits a pending request ─────────────────────────────────

function EditRequestModal({
  approval, airlines, onClose, onSaved,
}: {
  approval: Approval;
  airlines: AirlineOpt[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<FormState>({
    airline_name: approval.airline_name,
    airline_code: approval.airline_code ?? "",
    iata_numeric_code: approval.iata_numeric_code ?? "",
    iata_commission_pct:
      approval.iata_commission_pct != null ? String(approval.iata_commission_pct) : "",
    valid_from: approval.valid_from?.slice(0, 10) ?? "",
    valid_to: approval.valid_to?.slice(0, 10) ?? "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  /** Returns true when the edit saved, so the caller can chain approve. */
  const save = async (): Promise<boolean> => {
    if (!form.airline_name.trim()) { setError("Airline is required."); return false; }
    setError("");
    try {
      await api.patch(`/iata-commissions/approvals/${approval.id}`, formBody(form));
      return true;
    } catch (e) { setError(apiError(e)); return false; }
  };

  const handleSave = async () => {
    setSaving(true);
    if (await save()) { onSaved(); onClose(); }
    setSaving(false);
  };

  const handleSaveAndApprove = async () => {
    setSaving(true);
    if (await save()) {
      try {
        await api.patch(`/iata-commissions/approvals/${approval.id}/approve`);
        onSaved(); onClose();
      } catch (e) {
        // The edit is already persisted and the request is still pending — say
        // so rather than closing and losing the admin's work.
        setError(`Changes saved, but approval failed: ${apiError(e)}`);
        onSaved();
      }
    }
    setSaving(false);
  };

  return (
    <ModalShell title={`Edit Request — ${approval.airline_name}`} onClose={onClose}>
      <p className="text-[10px] text-gray-400 -mt-2 mb-3">
        Submitted by {approval.submitted_by.full_name} · they will see what you change
      </p>
      <div className="space-y-3">
        <CommissionFields form={form} setForm={setForm} airlines={airlines} />

        {error && <p className="text-[11px] text-red-500">{error}</p>}

        <div className="flex gap-2 pt-1">
          <button onClick={onClose} disabled={saving}
            className="flex-1 border border-gray-200 rounded-lg py-2 text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-50">
            Cancel
          </button>
          <button onClick={handleSave} disabled={saving}
            className="flex-1 border border-sky-500 text-sky-600 rounded-lg py-2 text-xs font-semibold hover:bg-sky-50 disabled:opacity-50">
            {saving ? "…" : "Save Changes"}
          </button>
          <button onClick={handleSaveAndApprove} disabled={saving}
            className="flex-1 bg-green-500 hover:bg-green-600 text-white rounded-lg py-2 text-xs font-semibold disabled:opacity-50">
            {saving ? "…" : "Save & Approve"}
          </button>
        </div>
      </div>
    </ModalShell>
  );
}

function RejectModal({
  approval, onClose, onDone,
}: { approval: Approval; onClose: () => void; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const handleReject = async () => {
    setSaving(true); setError("");
    try {
      await api.patch(`/iata-commissions/approvals/${approval.id}/reject`, {
        rejection_reason: reason || null,
      });
      onDone();
      onClose();
    } catch (e) { setError(apiError(e)); }
    finally { setSaving(false); }
  };

  return (
    <ModalShell title={`Reject IATA Commission — ${approval.airline_name}`} onClose={onClose}>
      <label className={LABEL}>Reason (optional)</label>
      <textarea value={reason} onChange={e => setReason(e.target.value)} rows={3}
        placeholder="Explain why this request is being rejected…"
        className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-300 bg-gray-50 resize-none" />
      {error && <p className="text-[11px] text-red-500 mt-2">{error}</p>}
      <div className="flex gap-3 pt-4">
        <button onClick={onClose}
          className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
        <button onClick={handleReject} disabled={saving}
          className="flex-1 bg-red-500 hover:bg-red-600 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50">
          {saving ? "Rejecting…" : "Reject"}
        </button>
      </div>
    </ModalShell>
  );
}

// ── badges ─────────────────────────────────────────────────────────────────

function RequestTypeBadge({ type }: { type: "new" | "update" }) {
  return type === "update"
    ? <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-50 text-amber-700 border border-amber-200">Update</span>
    : <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-green-50 text-green-700 border border-green-200">New</span>;
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { icon: React.ReactNode; cls: string }> = {
    pending: { icon: <Clock className="w-3 h-3" />, cls: "bg-yellow-50 text-yellow-700 border-yellow-200" },
    approved: { icon: <CheckCircle className="w-3 h-3" />, cls: "bg-green-50 text-green-700 border-green-200" },
    rejected: { icon: <XCircle className="w-3 h-3" />, cls: "bg-red-50 text-red-700 border-red-200" },
  };
  const s = map[status] ?? map.pending;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium border ${s.cls}`}>
      {s.icon} {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

// ── page ───────────────────────────────────────────────────────────────────

export default function IataCommissionPage() {
  const user = useAppSelector(s => s.auth.user);
  const isPlatformAdmin = canManageGlobalMasters(user?.role);
  const canSubmitRequest = canSubmitMasterRequest(user?.role);
  const canOpenRequestsTab = canViewMasterRequests(user?.role);

  const [rows, setRows] = useState<IataCommissionRow[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [airlines, setAirlines] = useState<AirlineOpt[]>([]);
  const [loading, setLoading] = useState(true);
  const [apiErr, setApiErr] = useState("");
  const [search, setSearch] = useState("");
  // The master list is Master Governance's to show; a tenant user only ever
  // sees what they themselves submitted. Defaulting the tab by role is what
  // enforces that — there is no control to switch back to the list.
  const [tab, setTab] = useState<"list" | "approvals">(isPlatformAdmin ? "list" : "approvals");

  const [showAdd, setShowAdd] = useState(false);
  const [editTarget, setEditTarget] = useState<IataCommissionRow | null>(null);
  const [rejectTarget, setRejectTarget] = useState<Approval | null>(null);
  const [editRequestTarget, setEditRequestTarget] = useState<Approval | null>(null);
  const [approvingId, setApprovingId] = useState<number | null>(null);
  const [diffTarget, setDiffTarget] = useState<Approval | null>(null);
  const [diffRecord, setDiffRecord] = useState<IataCommissionRow | null>(null);
  const [loadingDiff, setLoadingDiff] = useState(false);

  const fetchRows = useCallback(async () => {
    setLoading(true); setApiErr("");
    try {
      const { data } = await api.get<IataCommissionRow[]>("/iata-commissions/", { params: { search } });
      setRows(data);
    } catch (e) { setApiErr(apiError(e)); }
    finally { setLoading(false); }
  }, [search]);

  const fetchApprovals = useCallback(async () => {
    if (!canOpenRequestsTab) return;
    try {
      const { data } = await api.get<Approval[]>("/iata-commissions/approvals");
      setApprovals(data);
    } catch { /* ignore */ }
  }, [canOpenRequestsTab]);

  useEffect(() => { const t = setTimeout(fetchRows, 250); return () => clearTimeout(t); }, [fetchRows]);
  useEffect(() => { fetchApprovals(); }, [fetchApprovals]);
  useEffect(() => {
    api.get<AirlineOpt[]>("/airlines/", { params: { limit: 1000 } })
      .then(r => setAirlines(r.data))
      .catch(() => setAirlines([]));
  }, []);

  const toggle = async (row: IataCommissionRow) => {
    try {
      const { data } = await api.patch<IataCommissionRow>(`/iata-commissions/${row.id}`, { is_active: !row.is_active });
      setRows(p => p.map(r => r.id === row.id ? data : r));
    } catch { alert("Update failed."); }
  };

  const del = async (id: number) => {
    if (!confirm("Delete this IATA commission row? This cannot be undone.")) return;
    try { await api.delete(`/iata-commissions/${id}`); setRows(p => p.filter(r => r.id !== id)); }
    catch { alert("Delete failed."); }
  };

  const handleApprove = async (id: number) => {
    setApprovingId(id);
    try {
      await api.patch(`/iata-commissions/approvals/${id}/approve`);
      await Promise.all([fetchRows(), fetchApprovals()]);
    } catch (e) { alert(apiError(e)); }
    finally { setApprovingId(null); }
  };

  const handleViewDiff = async (approval: Approval) => {
    setDiffTarget(approval);
    setDiffRecord(null);
    // A "new" request has no master record to compare against — the modal just
    // drops that column and shows the admin's edit on its own.
    if (!approval.target_id) return;
    setLoadingDiff(true);
    try {
      const { data } = await api.get<IataCommissionRow>(`/iata-commissions/${approval.target_id}`);
      setDiffRecord(data);
    } catch { setDiffRecord(null); } finally { setLoadingDiff(false); }
  };

  const activeCount = rows.filter(r => r.is_active).length;
  const pendingCount = approvals.filter(a => a.status === "pending").length;
  const adminCols = isPlatformAdmin ? 8 : 7;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">Masters</p>
          <h1 className="text-xl font-bold text-gray-900">IATA Commission</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            {isPlatformAdmin
              ? `${rows.length} record${rows.length !== 1 ? "s" : ""} · ${activeCount} active`
              : `${approvals.length} submission${approvals.length !== 1 ? "s" : ""} · ${pendingCount} awaiting approval`}
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => { fetchRows(); fetchApprovals(); }} disabled={loading}
            className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-600 px-3 py-2 rounded-lg text-xs font-medium hover:bg-gray-50 disabled:opacity-50">
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          </button>
          {/* Only Master Governance sees the master list, so only it can export one. */}
          {isPlatformAdmin && (
            <ExportMasterButton resource="iata-commissions" filename="iata_commission_master.xlsx" />
          )}
          {canSubmitRequest && (
            <button onClick={() => setShowAdd(true)}
              className="flex items-center gap-1.5 text-white text-xs font-semibold px-3.5 py-2 rounded-lg shadow-sm hover:opacity-90"
              style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
              <Plus className="w-3.5 h-3.5" />
              {isPlatformAdmin ? "Add IATA Commission" : "Submit IATA Commission"}
            </button>
          )}
        </div>
      </div>

      <div className={`grid ${isPlatformAdmin ? "grid-cols-4" : "grid-cols-3"} gap-3`}>
        {/* Counts of master records are Master Governance's to show. A tenant
            user gets the shape of their own submissions instead. */}
        {(isPlatformAdmin ? [
          { label: "Total Records", value: rows.length, icon: Percent, color: "text-sky-600 bg-sky-50" },
          { label: "Active Records", value: activeCount, icon: TrendingUp, color: "text-emerald-600 bg-emerald-50" },
          { label: "With Validity Window", value: rows.filter(r => r.valid_from || r.valid_to).length, icon: Clock, color: "text-violet-600 bg-violet-50" },
          { label: "Pending Approvals", value: pendingCount, icon: Upload, color: "text-orange-600 bg-orange-50" },
        ] : [
          { label: "My Submissions", value: approvals.length, icon: Percent, color: "text-sky-600 bg-sky-50" },
          { label: "Awaiting Approval", value: pendingCount, icon: Upload, color: "text-orange-600 bg-orange-50" },
          { label: "Approved", value: approvals.filter(a => a.status === "approved").length, icon: TrendingUp, color: "text-emerald-600 bg-emerald-50" },
        ]).map(({ label, value, icon: Icon, color }) => (
          <div key={label} className="bg-white rounded-xl border border-gray-100 px-3 py-2 flex items-center gap-3 shadow-sm">
            <div className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${color}`}>
              <Icon className="w-4 h-4" />
            </div>
            <div>
              <p className="text-base font-bold text-gray-900 leading-none">{value}</p>
              <p className="text-[11px] text-gray-400 mt-0.5">{label}</p>
            </div>
          </div>
        ))}
      </div>

      <p className="text-xs text-gray-500">
        Per-airline IATA commission percentages and their validity periods.
        {!isPlatformAdmin && " This master is maintained by the platform team — submit a change and they will review it."}
      </p>

      {canOpenRequestsTab && isPlatformAdmin && (
        <div className="flex gap-1 bg-gray-100 rounded-xl p-1 w-fit">
          {(["list", "approvals"] as const).map(t => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-4 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                tab === t ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-700"
              }`}>
              {t === "list" ? "Commission List" : (
                <span className="flex items-center gap-1.5">
                  Pending Approvals
                  {pendingCount > 0 && t === "approvals" && (
                    <span className="bg-orange-500 text-white text-[9px] font-bold px-1.5 py-0.5 rounded-full">{pendingCount}</span>
                  )}
                </span>
              )}
            </button>
          ))}
        </div>
      )}

      {tab === "list" && isPlatformAdmin && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100">
            <div className="relative flex-1 min-w-48">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
              <input value={search} onChange={e => setSearch(e.target.value)}
                placeholder="Search airline, code or IATA numeric code…"
                className="w-full pl-8 pr-3 py-2 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-sky-400" />
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr style={{ background: "#1e4d8c" }}>
                  {["AIRLINE", "CODE", "IATA NUMERIC", "IATA COMM %", "VALID FROM", "VALID TO", "STATUS", "ACTIONS"].map(h => (
                    <th key={h} className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr><td colSpan={adminCols} className="px-4 py-12 text-center text-xs text-gray-400"><RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" />Loading…</td></tr>
                ) : apiErr ? (
                  <tr><td colSpan={adminCols} className="px-4 py-12 text-center text-xs text-red-400">{apiErr}</td></tr>
                ) : rows.length === 0 ? (
                  <tr><td colSpan={adminCols} className="px-4 py-12 text-center text-xs text-gray-400">
                    No IATA commissions yet. Add one or upload an XLS.
                  </td></tr>
                ) : rows.map((r, idx) => (
                  <tr key={r.id} className={`border-b border-gray-50 hover:bg-sky-50/30 ${idx % 2 ? "bg-gray-50/30" : "bg-white"}`}>
                    <td className="px-3 py-2 text-[11px] font-semibold text-gray-800">{r.airline_name}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{r.airline_code || "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{r.iata_numeric_code || "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{fmtPct(r.iata_commission_pct)}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{fmtDate(r.valid_from)}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{fmtDate(r.valid_to)}</td>
                    <td className="px-3 py-2">
                      <ActiveBadge active={r.is_active} onClick={() => toggle(r)} />
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-1">
                        <button onClick={() => setEditTarget(r)} className="p-1.5 hover:bg-blue-50 rounded-lg text-blue-400 hover:text-blue-600" title="Edit"><Edit2 className="w-3.5 h-3.5" /></button>
                        <button onClick={() => del(r.id)} className="p-1.5 hover:bg-red-50 rounded-lg text-red-400 hover:text-red-600" title="Delete"><Trash2 className="w-3.5 h-3.5" /></button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* A viewer can neither manage the master nor submit to it, so neither
          panel above applies. Say so rather than rendering an empty page. */}
      {!isPlatformAdmin && !canOpenRequestsTab && (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm px-4 py-16 text-center">
          <p className="text-sm font-medium text-gray-600">Nothing to show here</p>
          <p className="text-xs text-gray-400 mt-1 max-w-md mx-auto leading-relaxed">
            The master list is maintained by the platform team. Your role cannot submit
            master updates, so there are no submissions of your own to display.
          </p>
        </div>
      )}

      {tab === "approvals" && canOpenRequestsTab && (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100">
            <p className="text-xs font-semibold text-gray-700">
              {isPlatformAdmin ? "Pending Approval Requests" : "My Submitted IATA Commissions"}
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr style={{ background: "#1e4d8c" }}>
                  {["AIRLINE", "CODE", "IATA NUMERIC", "IATA COMM %", "VALID FROM", "VALID TO", "REQUEST",
                    ...(isPlatformAdmin ? ["SUBMITTED BY", "SUBMITTED AT", "ACTIONS"] : ["STATUS", "SUBMITTED AT", "REASON"])
                  ].map(h => (
                    <th key={h} className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {approvals.length === 0 ? (
                  <tr><td colSpan={10} className="px-4 py-10 text-center text-xs text-gray-400">
                    {isPlatformAdmin ? "No pending approvals." : "You haven't submitted any IATA commissions yet."}
                  </td></tr>
                ) : approvals.map((a, idx) => (
                  <tr key={a.id} className={`border-b border-gray-50 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50/30"}`}>
                    <td className="px-3 py-2 text-[11px] font-semibold text-gray-800">{a.airline_name}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{a.airline_code || "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{a.iata_numeric_code || "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{fmtPct(a.iata_commission_pct)}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{fmtDate(a.valid_from)}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{fmtDate(a.valid_to)}</td>
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-1 flex-wrap">
                        <RequestTypeBadge type={a.request_type} />
                        {/* So a second admin can tell this row has been touched. */}
                        {a.edited && (
                          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-100 text-amber-800 border border-amber-300">
                            Edited
                          </span>
                        )}
                      </div>
                    </td>
                    {isPlatformAdmin ? (
                      <>
                        <td className="px-3 py-2">
                          <p className="text-[11px] font-semibold text-gray-700">{a.submitted_by.full_name}</p>
                          <p className="text-[10px] text-gray-400">{a.submitted_by.email}</p>
                        </td>
                        <td className="px-3 py-2 text-[11px] text-gray-500">
                          {new Date(a.submitted_at).toLocaleDateString()}
                        </td>
                        <td className="px-3 py-2">
                          <div className="flex items-center gap-1.5 flex-wrap">
                            {/* Also meaningful on a "new" request once edited —
                                the modal then shows submitted vs. edited. */}
                            {(a.request_type === "update" || a.edited) && (
                              <button onClick={() => handleViewDiff(a)}
                                className="px-2.5 py-1 bg-amber-500 hover:bg-amber-600 text-white rounded-lg text-[10px] font-semibold">
                                View Changes
                              </button>
                            )}
                            <button onClick={() => setEditRequestTarget(a)}
                              className="flex items-center gap-1 px-2.5 py-1 bg-blue-500 hover:bg-blue-600 text-white rounded-lg text-[10px] font-semibold">
                              <Edit2 className="w-3 h-3" /> Edit
                            </button>
                            <button onClick={() => handleApprove(a.id)} disabled={approvingId === a.id}
                              className="flex items-center gap-1 px-2.5 py-1 bg-green-500 hover:bg-green-600 text-white rounded-lg text-[10px] font-semibold disabled:opacity-50">
                              <Check className="w-3 h-3" />
                              {approvingId === a.id ? "…" : "Approve"}
                            </button>
                            <button onClick={() => setRejectTarget(a)}
                              className="flex items-center gap-1 px-2.5 py-1 bg-red-500 hover:bg-red-600 text-white rounded-lg text-[10px] font-semibold">
                              <X className="w-3 h-3" /> Reject
                            </button>
                          </div>
                        </td>
                      </>
                    ) : (
                      <>
                        <td className="px-3 py-2">
                          <StatusBadge status={a.status} />
                          {/* Lives inside the STATUS cell so no column is added.
                              Shows for pending, approved and rejected alike. */}
                          {a.edited && (
                            <button onClick={() => handleViewDiff(a)}
                              title="See what the platform admin changed"
                              className="mt-1 flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-50 text-amber-700 border border-amber-200 hover:bg-amber-100">
                              View Admin Edits
                            </button>
                          )}
                        </td>
                        <td className="px-3 py-2 text-[11px] text-gray-500">
                          {new Date(a.submitted_at).toLocaleDateString()}
                        </td>
                        <td className="px-3 py-2 text-[11px] text-gray-500 max-w-xs truncate">
                          {a.rejection_reason ?? "—"}
                        </td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {showAdd && (
        <AddCommissionModal
          airlines={airlines}
          isPlatformAdmin={isPlatformAdmin}
          onClose={() => setShowAdd(false)}
          onSaved={() => { fetchRows(); fetchApprovals(); }}
        />
      )}
      {editTarget && (
        <EditCommissionModal
          row={editTarget}
          airlines={airlines}
          onClose={() => setEditTarget(null)}
          onSaved={fetchRows}
        />
      )}
      {rejectTarget && (
        <RejectModal
          approval={rejectTarget}
          onClose={() => setRejectTarget(null)}
          onDone={fetchApprovals}
        />
      )}
      {editRequestTarget && (
        <EditRequestModal
          approval={editRequestTarget}
          airlines={airlines}
          onClose={() => setEditRequestTarget(null)}
          onSaved={() => { fetchApprovals(); fetchRows(); }}
        />
      )}
      {diffTarget && (
        <MasterDiffModal
          title={`Change Diff — ${diffTarget.airline_name}`}
          subtitle={diffTarget.request_type === "update"
            ? `Updating IATA Commission ID #${diffTarget.target_id}`
            : "New IATA commission request"}
          fields={DIFF_FIELDS}
          // "Current" only exists for an update request.
          master={diffTarget.request_type === "update" ? diffRecord : null}
          // Once edited, the middle column is what the submitter actually sent;
          // otherwise the request row IS what they sent.
          submitted={diffTarget.edited ? (diffTarget.original_payload ?? {}) : diffTarget}
          edited={diffTarget.edited ? diffTarget : null}
          submittedLabel={isPlatformAdmin ? "User proposed" : "You submitted"}
          editedBy={diffTarget.edited_by}
          editedAt={diffTarget.edited_at}
          loading={loadingDiff}
          onClose={() => { setDiffTarget(null); setDiffRecord(null); }}
        />
      )}
    </div>
  );
}
