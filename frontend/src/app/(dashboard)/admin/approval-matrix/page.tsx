"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Check, CheckCircle2, Clock3, Filter, RefreshCw, Search, X, XCircle } from "lucide-react";
import api from "@/lib/api";
import { useAppSelector } from "@/store/hooks";
import { canManageGlobalMasters } from "@/lib/rbac";

type AirportApproval = {
  id: number;
  iata_code: string;
  country: string;
  categorization: string | null;
  continent: string | null;
  city_airport_name: string;
  status: "pending" | "approved" | "rejected";
  submitted_by: { id: number; full_name: string; email: string };
  submitted_at: string;
  rejection_reason: string | null;
  request_type: "new" | "update";
  target_id: number | null;
};

type AirlineApproval = {
  id: number;
  name: string;
  iata_code: string;
  icao_code: string | null;
  status: "pending" | "approved" | "rejected";
  submitted_by: { id: number; full_name: string; email: string };
  submitted_at: string;
  rejection_reason: string | null;
  request_type: "new" | "update";
  target_id: number | null;
};

type ClassApproval = {
  id: number;
  airline_name: string;
  class_type: string;
  class_code: string;
  airline_type: string | null;
  class_note: string | null;
  status: "pending" | "approved" | "rejected";
  submitted_by: { id: number; full_name: string; email: string };
  submitted_at: string;
  rejection_reason: string | null;
  request_type: "new" | "update";
  target_id: number | null;
};

type SupplierApproval = {
  id: number;
  name: string;
  vendor_name: string | null;
  vendor_type: string | null;
  branches: { name: string; iata_code: string }[] | null;
  contact_phone: string | null;
  gst_number: string | null;
  pan_number: string | null;
  notes: string | null;
  status: "pending" | "approved" | "rejected";
  submitted_by: { id: number; full_name: string; email: string };
  submitted_at: string;
  rejection_reason: string | null;
  request_type: "new" | "update";
  target_id: number | null;
};

type AirportRecord  = { id: number; iata_code: string; country: string; categorization: string | null; continent: string | null; city_airport_name: string };
type AirlineRecord  = { id: number; name: string; iata_code: string; icao_code: string | null };
type ClassRecord    = { id: number; airline_name: string; class_type: string; class_code: string; airline_type: string | null; class_note: string | null };
type SupplierRecord = { id: number; name: string; vendor_name: string | null; vendor_type: string | null; branches: { name: string; iata_code: string }[] | null; contact_phone: string | null; gst_number: string | null; pan_number: string | null; notes: string | null };
type CurrentRecord  = AirportRecord | AirlineRecord | ClassRecord | SupplierRecord;

type ApprovalItem = {
  key: string;
  type: "airport" | "airline" | "class" | "supplier";
  id: number;
  code: string;
  name: string;
  status: "pending" | "approved" | "rejected";
  submitted_by: { id: number; full_name: string; email: string };
  submitted_at: string;
  rejection_reason: string | null;
  requestType: "new" | "update";
  targetId: number | null;
  rawData: Record<string, unknown>;
};

// ── diff modal ─────────────────────────────────────────────────────────────

function formatDiffVal(key: string, val: unknown): string {
  if (key === "branches") {
    if (!Array.isArray(val) || val.length === 0) return "";
    return (val as { name: string; iata_code: string }[])
      .map((b) => `${b.name} (${b.iata_code})`)
      .join(", ");
  }
  return String(val ?? "");
}

const DIFF_FIELDS: Record<ApprovalItem["type"], { label: string; key: string }[]> = {
  airport: [
    { label: "IATA Code",       key: "iata_code" },
    { label: "Country",         key: "country" },
    { label: "Categorization",  key: "categorization" },
    { label: "Continent",       key: "continent" },
    { label: "City / Airport",  key: "city_airport_name" },
  ],
  airline: [
    { label: "Airline Name",      key: "name" },
    { label: "IATA Code",         key: "iata_code" },
    { label: "ICAO Code",         key: "icao_code" },
  ],
  class: [
    { label: "Airline Name",  key: "airline_name" },
    { label: "Class Type",    key: "class_type" },
    { label: "Class Code",    key: "class_code" },
    { label: "Airline Type",  key: "airline_type" },
    { label: "Class Note",    key: "class_note" },
  ],
  supplier: [
    { label: "Name",         key: "name" },
    { label: "Display Name", key: "vendor_name" },
    { label: "Type",         key: "vendor_type" },
    { label: "Branches",     key: "branches" },
    { label: "Contact",      key: "contact_phone" },
    { label: "GST Number",   key: "gst_number" },
    { label: "PAN Number",   key: "pan_number" },
    { label: "Remarks",      key: "notes" },
  ],
};

function ApprovalDiffModal({
  item,
  currentRecord,
  loading,
  onClose,
}: {
  item: ApprovalItem;
  currentRecord: CurrentRecord | null;
  loading: boolean;
  onClose: () => void;
}) {
  const fields = DIFF_FIELDS[item.type];
  const cur = currentRecord as Record<string, unknown> | null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-xl">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-sm font-bold text-gray-900">Change Diff — {item.code}</h2>
            <p className="text-[10px] text-gray-400 mt-0.5">
              Updating {item.type.charAt(0).toUpperCase() + item.type.slice(1)} ID #{item.targetId}
            </p>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg">
            <X className="w-4 h-4 text-gray-500" />
          </button>
        </div>
        <div className="px-6 py-4">
          {loading ? (
            <div className="py-8 text-center text-xs text-gray-400">
              <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" />
              Loading current record...
            </div>
          ) : !cur ? (
            <p className="text-xs text-red-500 py-4 text-center">
              Could not load the current {item.type} record.
            </p>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="text-left py-2 pr-3 text-[10px] font-semibold text-gray-400 uppercase tracking-wide w-36">Field</th>
                  <th className="text-left py-2 pr-3 text-[10px] font-semibold text-gray-400 uppercase tracking-wide">Current</th>
                  <th className="text-left py-2 text-[10px] font-semibold text-gray-400 uppercase tracking-wide">Proposed</th>
                </tr>
              </thead>
              <tbody>
                {fields.map(({ label, key }) => {
                  const currentVal = formatDiffVal(key, cur[key]);
                  const proposed   = formatDiffVal(key, item.rawData[key]);
                  const changed   = currentVal !== proposed;
                  return (
                    <tr key={key} className={`border-b border-gray-50 ${changed ? "bg-amber-50/60" : ""}`}>
                      <td className="py-2 pr-3 font-semibold text-gray-600 text-[11px]">{label}</td>
                      <td className="py-2 pr-3 text-gray-500">{currentVal || "—"}</td>
                      <td className={`py-2 font-medium ${changed ? "text-amber-700" : "text-gray-700"}`}>
                        {proposed || "—"}
                        {changed && (
                          <span className="ml-1.5 text-[9px] bg-amber-200 text-amber-800 px-1 py-0.5 rounded font-bold">
                            CHANGED
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
        <div className="px-6 pb-4">
          <button onClick={onClose} className="w-full border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

// ── status badge ────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: ApprovalItem["status"] }) {
  if (status === "approved") {
    return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium border bg-green-50 text-green-700 border-green-200"><CheckCircle2 className="w-3 h-3" />Approved</span>;
  }
  if (status === "rejected") {
    return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium border bg-red-50 text-red-700 border-red-200"><XCircle className="w-3 h-3" />Rejected</span>;
  }
  return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium border bg-yellow-50 text-yellow-700 border-yellow-200"><Clock3 className="w-3 h-3" />Pending</span>;
}

// ── page ────────────────────────────────────────────────────────────────────

export default function ApprovalMatrixPage() {
  const router = useRouter();
  const user = useAppSelector((s) => s.auth.user);
  const isPlatformAdmin = canManageGlobalMasters(user?.role);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [items, setItems] = useState<ApprovalItem[]>([]);
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<"all" | "airport" | "airline" | "class" | "supplier">("all");
  const [statusFilter, setStatusFilter] = useState<"all" | "pending" | "approved" | "rejected">("pending");
  const [actingKey, setActingKey] = useState<string | null>(null);
  const [rejectingKey, setRejectingKey] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [diffTarget, setDiffTarget] = useState<ApprovalItem | null>(null);
  const [diffRecord, setDiffRecord] = useState<CurrentRecord | null>(null);
  const [loadingDiff, setLoadingDiff] = useState(false);

  const fetchApprovals = async () => {
    if (!isPlatformAdmin) return;
    setLoading(true);
    setError("");
    try {
      const [airportsRes, airlinesRes, classesRes, suppliersRes] = await Promise.all([
        api.get<AirportApproval[]>("/airports/approvals"),
        api.get<AirlineApproval[]>("/airlines/approvals"),
        api.get<ClassApproval[]>("/classes/approvals"),
        api.get<SupplierApproval[]>("/suppliers/approvals"),
      ]);

      const airportItems: ApprovalItem[] = airportsRes.data.map((a) => ({
        key: `airport-${a.id}`,
        type: "airport",
        id: a.id,
        code: a.iata_code,
        name: a.city_airport_name,
        status: a.status,
        submitted_by: a.submitted_by,
        submitted_at: a.submitted_at,
        rejection_reason: a.rejection_reason,
        requestType: a.request_type ?? "new",
        targetId: a.target_id ?? null,
        rawData: a as unknown as Record<string, unknown>,
      }));

      const airlineItems: ApprovalItem[] = airlinesRes.data.map((a) => ({
        key: `airline-${a.id}`,
        type: "airline",
        id: a.id,
        code: a.iata_code,
        name: a.name,
        status: a.status,
        submitted_by: a.submitted_by,
        submitted_at: a.submitted_at,
        rejection_reason: a.rejection_reason,
        requestType: a.request_type ?? "new",
        targetId: a.target_id ?? null,
        rawData: a as unknown as Record<string, unknown>,
      }));

      const classItems: ApprovalItem[] = classesRes.data.map((a) => ({
        key: `class-${a.id}`,
        type: "class",
        id: a.id,
        code: a.class_code,
        name: `${a.airline_name} / ${a.class_type}`,
        status: a.status,
        submitted_by: a.submitted_by,
        submitted_at: a.submitted_at,
        rejection_reason: a.rejection_reason,
        requestType: a.request_type ?? "new",
        targetId: a.target_id ?? null,
        rawData: a as unknown as Record<string, unknown>,
      }));

      const supplierItems: ApprovalItem[] = suppliersRes.data.map((a) => ({
        key: `supplier-${a.id}`,
        type: "supplier" as const,
        id: a.id,
        code: a.name,
        name: a.vendor_name ?? a.name,
        status: a.status,
        submitted_by: a.submitted_by,
        submitted_at: a.submitted_at,
        rejection_reason: a.rejection_reason,
        requestType: a.request_type ?? "new",
        targetId: a.target_id ?? null,
        rawData: a as unknown as Record<string, unknown>,
      }));

      setItems([...airportItems, ...airlineItems, ...classItems, ...supplierItems].sort((x, y) =>
        new Date(y.submitted_at).getTime() - new Date(x.submitted_at).getTime()
      ));
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      const msg = Array.isArray(detail)
        ? (detail as { msg?: string }[]).map((d) => d.msg ?? JSON.stringify(d)).join("; ")
        : typeof detail === "string"
          ? detail
          : "Failed to load approval requests.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleViewDiff = async (item: ApprovalItem) => {
    if (!item.targetId) return;
    setDiffTarget(item);
    setLoadingDiff(true);
    setDiffRecord(null);
    try {
      const base = item.type === "airport" ? "/airports"
                 : item.type === "airline" ? "/airlines"
                 : item.type === "supplier" ? "/suppliers"
                 : "/classes";
      const { data } = await api.get<CurrentRecord>(`${base}/${item.targetId}`);
      setDiffRecord(data);
    } catch { setDiffRecord(null); }
    finally { setLoadingDiff(false); }
  };

  useEffect(() => {
    if (!isPlatformAdmin) {
      router.replace("/");
      return;
    }
    fetchApprovals();
  }, [isPlatformAdmin, router]);

  if (!isPlatformAdmin) return null;

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return items.filter((item) => {
      if (typeFilter !== "all" && item.type !== typeFilter) return false;
      if (statusFilter !== "all" && item.status !== statusFilter) return false;
      if (!q) return true;
      return (
        item.code.toLowerCase().includes(q) ||
        item.name.toLowerCase().includes(q) ||
        item.submitted_by.full_name.toLowerCase().includes(q) ||
        item.submitted_by.email.toLowerCase().includes(q)
      );
    });
  }, [items, query, typeFilter, statusFilter]);

  const counts = useMemo(() => ({
    total: items.length,
    pending: items.filter((i) => i.status === "pending").length,
    approved: items.filter((i) => i.status === "approved").length,
    rejected: items.filter((i) => i.status === "rejected").length,
  }), [items]);

  const approve = async (item: ApprovalItem) => {
    if (item.status !== "pending") return;
    setActingKey(item.key);
    try {
      const base = item.type === "airport"
        ? "/airports/approvals"
        : item.type === "airline"
          ? "/airlines/approvals"
          : item.type === "supplier"
            ? "/suppliers/approvals"
            : "/classes/approvals";
      await api.patch(`${base}/${item.id}/approve`);
      await fetchApprovals();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      const msg = Array.isArray(detail)
        ? (detail as { msg?: string }[]).map((d) => d.msg ?? JSON.stringify(d)).join("; ")
        : typeof detail === "string" ? detail : "Failed to approve request.";
      alert(msg);
    } finally {
      setActingKey(null);
    }
  };

  const reject = async () => {
    if (!rejectingKey) return;
    const item = items.find((x) => x.key === rejectingKey);
    if (!item || item.status !== "pending") return;
    setActingKey(item.key);
    try {
      const base = item.type === "airport"
        ? "/airports/approvals"
        : item.type === "airline"
          ? "/airlines/approvals"
          : item.type === "supplier"
            ? "/suppliers/approvals"
            : "/classes/approvals";
      await api.patch(`${base}/${item.id}/reject`, { rejection_reason: rejectReason || null });
      setRejectingKey(null);
      setRejectReason("");
      await fetchApprovals();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      const msg = Array.isArray(detail)
        ? (detail as { msg?: string }[]).map((d) => d.msg ?? JSON.stringify(d)).join("; ")
        : typeof detail === "string" ? detail : "Failed to reject request.";
      alert(msg);
    } finally {
      setActingKey(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Approval Inbox</h1>
          <p className="text-sm text-gray-500 mt-0.5">All master approval requests in one place</p>
        </div>
        <button
          onClick={fetchApprovals}
          disabled={loading}
          className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      <div className="grid grid-cols-4 gap-3">
        {[
          { label: "Total", value: counts.total, cls: "bg-blue-50 text-blue-700 border-blue-200" },
          { label: "Pending", value: counts.pending, cls: "bg-yellow-50 text-yellow-700 border-yellow-200" },
          { label: "Approved", value: counts.approved, cls: "bg-green-50 text-green-700 border-green-200" },
          { label: "Rejected", value: counts.rejected, cls: "bg-red-50 text-red-700 border-red-200" },
        ].map((s) => (
          <div key={s.label} className={`rounded-xl border px-4 py-3 ${s.cls}`}>
            <p className="text-lg font-bold leading-none">{s.value}</p>
            <p className="text-xs mt-1">{s.label}</p>
          </div>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-3 flex items-center gap-2 flex-wrap">
        <div className="relative flex-1 min-w-64">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search code, name, requester..."
            className="w-full pl-8 pr-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-200"
          />
        </div>
        <div className="flex items-center gap-1.5 text-xs text-gray-500 ml-1">
          <Filter className="w-3.5 h-3.5" /> Filters
        </div>
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value as typeof typeFilter)}
          className="border border-gray-200 rounded-lg px-2.5 py-2 text-sm bg-white"
        >
          <option value="all">All Types</option>
          <option value="airport">Airport</option>
          <option value="airline">Airline</option>
          <option value="class">Class</option>
          <option value="supplier">Supplier</option>
        </select>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as typeof statusFilter)}
          className="border border-gray-200 rounded-lg px-2.5 py-2 text-sm bg-white"
        >
          <option value="all">All Status</option>
          <option value="pending">Pending</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
        </select>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-xs uppercase text-gray-500">
            <tr>
              <th className="px-4 py-3 text-left">Type</th>
              <th className="px-4 py-3 text-left">Request</th>
              <th className="px-4 py-3 text-left">Code</th>
              <th className="px-4 py-3 text-left">Name</th>
              <th className="px-4 py-3 text-left">Requested By</th>
              <th className="px-4 py-3 text-left">Submitted</th>
              <th className="px-4 py-3 text-left">Status</th>
              <th className="px-4 py-3 text-center">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading ? (
              <tr>
                <td colSpan={8} className="px-4 py-12 text-center text-sm text-gray-400">Loading approvals...</td>
              </tr>
            ) : error ? (
              <tr>
                <td colSpan={8} className="px-4 py-12 text-center text-sm text-red-500">{error}</td>
              </tr>
            ) : filtered.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-4 py-12 text-center text-sm text-gray-400">No approval requests found.</td>
              </tr>
            ) : filtered.map((item) => (
              <tr key={item.key} className="hover:bg-gray-50">
                <td className="px-4 py-3">
                  <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                    item.type === "airport"
                      ? "bg-teal-50 text-teal-700"
                      : item.type === "airline"
                        ? "bg-sky-50 text-sky-700"
                        : item.type === "supplier"
                          ? "bg-purple-50 text-purple-700"
                          : "bg-emerald-50 text-emerald-700"
                  }`}>
                    {item.type}
                  </span>
                </td>
                <td className="px-4 py-3">
                  {item.requestType === "update" ? (
                    <span
                      className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold bg-amber-50 text-amber-700 border border-amber-200"
                      title={item.targetId ? `Updating record ID: ${item.targetId}` : "Update existing record"}
                    >
                      Update
                    </span>
                  ) : (
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold bg-green-50 text-green-700 border border-green-200">
                      New
                    </span>
                  )}
                </td>
                <td className="px-4 py-3 font-mono text-xs font-semibold text-gray-700">{item.code}</td>
                <td className="px-4 py-3 text-sm text-gray-800">{item.name}</td>
                <td className="px-4 py-3">
                  <p className="text-sm font-medium text-gray-800">{item.submitted_by.full_name}</p>
                  <p className="text-xs text-gray-400">{item.submitted_by.email}</p>
                </td>
                <td className="px-4 py-3 text-xs text-gray-500">{new Date(item.submitted_at).toLocaleString()}</td>
                <td className="px-4 py-3"><StatusBadge status={item.status} /></td>
                <td className="px-4 py-3">
                  {item.status === "pending" ? (
                    <div className="flex items-center justify-center gap-1.5 flex-wrap">
                      {item.requestType === "update" && (
                        <button
                          onClick={() => handleViewDiff(item)}
                          className="px-2.5 py-1 text-[10px] font-semibold rounded-lg bg-amber-500 text-white hover:bg-amber-600 inline-flex items-center gap-1"
                        >
                          View Changes
                        </button>
                      )}
                      <button
                        onClick={() => approve(item)}
                        disabled={actingKey === item.key}
                        className="px-2.5 py-1 text-xs font-semibold rounded-lg bg-green-500 text-white hover:bg-green-600 disabled:opacity-50 inline-flex items-center gap-1"
                      >
                        <Check className="w-3 h-3" /> Approve
                      </button>
                      <button
                        onClick={() => { setRejectingKey(item.key); setRejectReason(""); }}
                        disabled={actingKey === item.key}
                        className="px-2.5 py-1 text-xs font-semibold rounded-lg bg-red-500 text-white hover:bg-red-600 disabled:opacity-50"
                      >
                        Reject
                      </button>
                    </div>
                  ) : (
                    <span className="text-xs text-gray-400 block text-center">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {rejectingKey && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md">
            <div className="px-5 py-4 border-b border-gray-100">
              <h2 className="text-sm font-bold text-gray-900">Reject Request</h2>
            </div>
            <div className="px-5 py-4">
              <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Reason (optional)</label>
              <textarea
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                rows={3}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-200"
                placeholder="Add rejection reason..."
              />
            </div>
            <div className="px-5 pb-5 flex gap-2">
              <button
                onClick={() => { setRejectingKey(null); setRejectReason(""); }}
                className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={reject}
                className="flex-1 bg-red-500 hover:bg-red-600 text-white rounded-lg py-2 text-sm font-semibold"
              >
                Confirm Reject
              </button>
            </div>
          </div>
        </div>
      )}

      {diffTarget && (
        <ApprovalDiffModal
          item={diffTarget}
          currentRecord={diffRecord}
          loading={loadingDiff}
          onClose={() => { setDiffTarget(null); setDiffRecord(null); }}
        />
      )}
    </div>
  );
}
