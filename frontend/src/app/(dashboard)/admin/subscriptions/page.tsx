"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Building2, CheckCircle2, Clock3, CreditCard, Filter, Lock, RefreshCw, Search, Trash2, User2,
} from "lucide-react";
import api from "@/lib/api";
import { useAppSelector } from "@/store/hooks";
import { canManageGlobalMasters } from "@/lib/rbac";
import { INPUT, LABEL, ModalShell, apiError } from "@/components/userMaster/shared";
import DeleteWorkspaceModal from "@/components/admin/DeleteWorkspaceModal";

type PlanStatus = "free" | "trial" | "active" | "expired" | "suspended";

type TenantPlan = {
  id: number;
  name: string | null;
  domain: string | null;
  tenant_type: "corporate" | "individual";
  plan_status: PlanStatus;
  plan_expires_at: string | null;
  plan_activated_at: string | null;
  plan_note: string | null;
  created_at: string;
  has_active_plan: boolean;
  user_count: number;
  // Every table this workspace fills, totalled. Deals and tickets alone said too
  // little — a workspace living in BSP and vendor statements read as 0.
  record_count: number;
  // {label: rows}, non-zero entries only, in the order the backend registry
  // declares them. Feeds the hover panel.
  record_breakdown: Record<string, number>;
  owner_email: string | null;
  owner_name: string | null;
};

type Stats = {
  total: number; active: number; free: number; trial: number; expired: number; suspended: number;
};

const STATUS_OPTIONS: { value: PlanStatus; label: string; hint: string }[] = [
  { value: "active",    label: "Active",    hint: "Full access to the platform." },
  { value: "trial",     label: "Trial",     hint: "Full access. Set an expiry date to end it automatically." },
  { value: "free",      label: "Free",      hint: "Frozen — the workspace sees the 'No active plan' screen." },
  { value: "expired",   label: "Expired",   hint: "Frozen — was paying, subscription lapsed." },
  { value: "suspended", label: "Suspended", hint: "Frozen — switched off deliberately." },
];

const CHIP: Record<PlanStatus, string> = {
  active:    "bg-green-50 text-green-700 border-green-200",
  trial:     "bg-sky-50 text-sky-700 border-sky-200",
  free:      "bg-gray-50 text-gray-500 border-gray-200",
  expired:   "bg-amber-50 text-amber-700 border-amber-200",
  suspended: "bg-red-50 text-red-600 border-red-200",
};

function fmtDate(v: string | null) {
  if (!v) return "—";
  return new Date(v).toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" });
}

/** yyyy-MM-dd for <input type="date">, or "" when unset. */
function toDateInput(v: string | null) {
  return v ? new Date(v).toISOString().slice(0, 10) : "";
}

function StatTile({ icon: Icon, label, value, tone }: {
  icon: typeof CreditCard; label: string; value: number; tone: string;
}) {
  return (
    <div className="bg-white border border-gray-100 rounded-xl px-4 py-3 flex items-center gap-3">
      <div className={`grid h-9 w-9 place-items-center rounded-lg ${tone}`}>
        <Icon className="h-4 w-4" />
      </div>
      <div>
        <p className="text-lg font-bold text-gray-900 leading-none">{value}</p>
        <p className="text-[11px] text-gray-400 mt-1">{label}</p>
      </div>
    </div>
  );
}

/**
 * The Records total, with the per-table breakdown behind a hover.
 *
 * The panel is `position: fixed` rather than `absolute` on purpose: the table
 * sits inside `overflow-x-auto`, and a non-visible overflow on one axis makes the
 * browser clip the other too — an absolutely positioned panel would be cut off at
 * the first and last rows. Fixed escapes that, and no ancestor of this table sets
 * transform/filter/will-change, so it resolves against the viewport.
 */
function RecordsCell({ total, breakdown }: {
  total: number; breakdown: Record<string, number>;
}) {
  const [at, setAt] = useState<{ x: number; y: number } | null>(null);
  const entries = Object.entries(breakdown ?? {});

  // A fixed panel does not travel with the scroll container, so drop it rather
  // than let it hang over unrelated rows.
  useEffect(() => {
    if (!at) return;
    const close = () => setAt(null);
    window.addEventListener("scroll", close, true);
    return () => window.removeEventListener("scroll", close, true);
  }, [at]);

  if (!total) {
    return <td className="px-4 py-3 text-xs tabular-nums"><span className="text-gray-300">0</span></td>;
  }

  return (
    <td
      className="px-4 py-3 text-xs tabular-nums"
      onMouseEnter={(e) => {
        const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
        setAt({ x: r.left, y: r.bottom + 6 });
      }}
      onMouseLeave={() => setAt(null)}
    >
      <span className="text-gray-700 font-medium cursor-default border-b border-dotted border-gray-300">
        {total.toLocaleString()}
      </span>
      {at && entries.length > 0 && (
        <div
          className="fixed z-50 bg-white border border-gray-200 rounded-lg shadow-lg py-1.5 px-2 min-w-44 pointer-events-none"
          style={{ left: at.x, top: at.y }}
        >
          <p className="text-[9px] uppercase tracking-wide text-gray-400 px-1 pb-1">Records by source</p>
          {entries.map(([label, n]) => (
            <div key={label} className="flex items-center justify-between gap-6 px-1 py-0.5">
              <span className="text-[10px] text-gray-600 whitespace-nowrap">{label}</span>
              <span className="text-[10px] text-gray-900 font-medium tabular-nums">{n.toLocaleString()}</span>
            </div>
          ))}
        </div>
      )}
    </td>
  );
}

export default function SubscriptionsPage() {
  const router = useRouter();
  const user = useAppSelector((s) => s.auth.user);
  const isPlatformAdmin = canManageGlobalMasters(user?.role);

  const [rows, setRows] = useState<TenantPlan[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | PlanStatus>("all");

  const [editing, setEditing] = useState<TenantPlan | null>(null);
  const [form, setForm] = useState<{ plan_status: PlanStatus; expires: string; note: string }>({
    plan_status: "active", expires: "", note: "",
  });
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");

  const [deleting, setDeleting] = useState<TenantPlan | null>(null);
  // Survives the modal closing, so the operator sees what actually went.
  const [deleteNotice, setDeleteNotice] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params: Record<string, string> = {};
      if (query.trim()) params.q = query.trim();
      if (statusFilter !== "all") params.plan_status = statusFilter;
      const [list, s] = await Promise.all([
        api.get<TenantPlan[]>("/subscriptions/", { params }),
        api.get<Stats>("/subscriptions/stats"),
      ]);
      setRows(list.data);
      setStats(s.data);
    } catch (e) {
      setError(apiError(e));
    } finally {
      setLoading(false);
    }
  }, [query, statusFilter]);

  useEffect(() => {
    if (!isPlatformAdmin) {
      router.replace("/dashboard");
      return;
    }
    load();
  }, [isPlatformAdmin, router, load]);

  if (!isPlatformAdmin) return null;

  const openEditor = (t: TenantPlan) => {
    setEditing(t);
    setFormError("");
    setForm({
      plan_status: t.plan_status,
      expires: toDateInput(t.plan_expires_at),
      note: t.plan_note ?? "",
    });
  };

  const save = async () => {
    if (!editing) return;
    setSaving(true);
    setFormError("");
    try {
      // Send end-of-day so an expiry of "31 Dec" covers the whole of the 31st.
      await api.patch(`/subscriptions/${editing.id}`, {
        plan_status: form.plan_status,
        plan_expires_at: form.expires ? `${form.expires}T23:59:59` : null,
        plan_note: form.note.trim() || null,
      });
      setEditing(null);
      await load();
    } catch (e) {
      setFormError(apiError(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-gray-900">Subscriptions</h1>
        <p className="text-xs text-gray-400 mt-1">
          Every workspace on the platform. A workspace without an active plan can sign in but is
          frozen behind the &ldquo;No active plan&rdquo; screen until you switch it on here.
        </p>
      </div>

      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatTile icon={Building2}    label="Workspaces" value={stats.total}                    tone="bg-slate-50 text-slate-500" />
          <StatTile icon={CheckCircle2} label="Active"     value={stats.active + stats.trial}      tone="bg-green-50 text-green-600" />
          <StatTile icon={Lock}         label="Free"       value={stats.free}                      tone="bg-gray-50 text-gray-500" />
          <StatTile icon={Clock3}       label="Lapsed"     value={stats.expired + stats.suspended} tone="bg-amber-50 text-amber-600" />
        </div>
      )}

      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative flex-1 min-w-56">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && load()}
            placeholder="Search workspace name, domain or owner email…"
            className="w-full pl-8 pr-3 py-2 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-sky-400"
          />
        </div>
        <div className="relative">
          <Filter className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none" />
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as "all" | PlanStatus)}
            className="pl-8 pr-3 py-2 border border-gray-200 rounded-lg text-xs bg-white focus:outline-none focus:ring-1 focus:ring-sky-400"
          >
            <option value="all">All statuses</option>
            {STATUS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-600 px-3 py-2 rounded-lg text-xs font-medium hover:bg-gray-50 disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-600 text-xs rounded-lg px-3 py-2">{error}</div>
      )}

      {deleteNotice && (
        <div className="flex items-start justify-between gap-3 bg-amber-50 border border-amber-200 text-amber-800 text-xs rounded-lg px-3 py-2">
          <span>{deleteNotice}</span>
          <button onClick={() => setDeleteNotice("")} className="text-amber-500 hover:text-amber-700 shrink-0">
            Dismiss
          </button>
        </div>
      )}

      <div className="bg-white border border-gray-100 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead className="bg-gray-50 border-b border-gray-100">
              <tr className="text-[10px] uppercase tracking-wide text-gray-400">
                <th className="px-4 py-2.5 font-semibold">Workspace</th>
                <th className="px-4 py-2.5 font-semibold">Owner</th>
                <th className="px-4 py-2.5 font-semibold">Users</th>
                <th className="px-4 py-2.5 font-semibold">Records</th>
                <th className="px-4 py-2.5 font-semibold">Plan</th>
                <th className="px-4 py-2.5 font-semibold">Expires</th>
                <th className="px-4 py-2.5 font-semibold">Joined</th>
                <th className="px-4 py-2.5 font-semibold text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {loading && (
                <tr><td colSpan={8} className="px-4 py-8 text-center text-xs text-gray-400">Loading…</td></tr>
              )}
              {!loading && rows.length === 0 && (
                <tr><td colSpan={8} className="px-4 py-8 text-center text-xs text-gray-400">No workspaces match.</td></tr>
              )}
              {!loading && rows.map((t) => (
                <tr key={t.id} className="hover:bg-gray-50/60">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      {t.tenant_type === "corporate"
                        ? <Building2 className="h-3.5 w-3.5 text-slate-400 shrink-0" />
                        : <User2 className="h-3.5 w-3.5 text-slate-400 shrink-0" />}
                      <div className="min-w-0">
                        <p className="text-xs font-semibold text-gray-900 truncate">{t.name || "Untitled workspace"}</p>
                        <p className="text-[10px] text-gray-400 truncate">{t.domain || t.tenant_type}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <p className="text-xs text-gray-700 truncate">{t.owner_name || "—"}</p>
                    <p className="text-[10px] text-gray-400 truncate">{t.owner_email || "—"}</p>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-600">{t.user_count}</td>
                  {/* Usage at a glance — a zero reads as "signed up but never used".
                      Hover the number for which tables it came from. */}
                  <RecordsCell total={t.record_count} breakdown={t.record_breakdown} />
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium border ${CHIP[t.plan_status]}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${t.has_active_plan ? "bg-green-500" : "bg-gray-400"}`} />
                      {t.plan_status}
                    </span>
                    {/* Stored status says active but the date has passed — the
                        backend already refuses this workspace's requests. */}
                    {!t.has_active_plan && (t.plan_status === "active" || t.plan_status === "trial") && (
                      <span className="ml-1.5 text-[10px] text-amber-600">lapsed</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-600">{fmtDate(t.plan_expires_at)}</td>
                  <td className="px-4 py-3 text-xs text-gray-500">{fmtDate(t.created_at)}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-1.5">
                      <button
                        onClick={() => openEditor(t)}
                        className="inline-flex items-center gap-1.5 text-white px-3 py-1.5 rounded-lg text-[11px] font-medium"
                        style={{ background: "#7c3aed" }}
                      >
                        <CreditCard className="w-3 h-3" /> Manage plan
                      </button>
                      <button
                        onClick={() => setDeleting(t)}
                        title="Delete this workspace's records, or the whole workspace"
                        className="inline-flex items-center justify-center h-[26px] w-[26px] rounded-lg border border-gray-200 text-gray-400 hover:border-red-200 hover:bg-red-50 hover:text-red-600 transition-colors"
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {editing && (
        <ModalShell title={`Plan — ${editing.name || editing.domain || `Workspace #${editing.id}`}`} onClose={() => setEditing(null)}>
          <div className="space-y-4">
            <div className="bg-gray-50 border border-gray-100 rounded-lg px-3 py-2 text-[11px] text-gray-500">
              {editing.owner_email || "no owner"} · {editing.user_count} user{editing.user_count !== 1 ? "s" : ""} ·{" "}
              {editing.tenant_type}
              {editing.plan_activated_at && <> · activated {fmtDate(editing.plan_activated_at)}</>}
            </div>

            <div>
              <label className={LABEL}>Plan status</label>
              <select
                value={form.plan_status}
                onChange={(e) => setForm({ ...form, plan_status: e.target.value as PlanStatus })}
                className={INPUT}
              >
                {STATUS_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
              <p className="mt-1 text-[10px] text-gray-400">
                {STATUS_OPTIONS.find((o) => o.value === form.plan_status)?.hint}
              </p>
            </div>

            <div>
              <label className={LABEL}>Expires on (optional)</label>
              <input
                type="date"
                value={form.expires}
                onChange={(e) => setForm({ ...form, expires: e.target.value })}
                className={INPUT}
              />
              <p className="mt-1 text-[10px] text-gray-400">
                Leave empty for no expiry. The workspace freezes by itself the day after this date.
              </p>
            </div>

            <div>
              <label className={LABEL}>Internal note (optional)</label>
              <input
                value={form.note}
                onChange={(e) => setForm({ ...form, note: e.target.value })}
                placeholder="e.g. 12 months, invoice #1042"
                className={INPUT}
                maxLength={255}
              />
              <p className="mt-1 text-[10px] text-gray-400">Never shown to the workspace.</p>
            </div>

            {formError && <p className="text-[11px] text-red-500">{formError}</p>}

            <div className="flex gap-2 pt-1">
              <button
                onClick={() => setEditing(null)}
                className="flex-1 border border-gray-200 text-gray-600 rounded-lg py-2 text-sm font-medium hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={save}
                disabled={saving}
                className="flex-1 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50"
                style={{ background: "linear-gradient(135deg, #7c3aed, #6d28d9)" }}
              >
                {saving ? "Saving…" : "Save plan"}
              </button>
            </div>
            <p className="text-[10px] text-gray-400 text-center">
              Takes effect on the workspace&apos;s next request — nobody has to sign out and back in.
            </p>
          </div>
        </ModalShell>
      )}

      {deleting && (
        <DeleteWorkspaceModal
          tenantId={deleting.id}
          fallbackName={deleting.name || deleting.domain || `Workspace #${deleting.id}`}
          onClose={() => setDeleting(null)}
          onDeleted={(result) => {
            const who = result.tenant_name || `Workspace #${result.tenant_id}`;
            const n = result.total.toLocaleString();
            const rows = `${n} record${result.total !== 1 ? "s" : ""}`;
            const what = result.deleted.length
              ? ` (${result.deleted.map((d) => `${d.label} ${d.rows.toLocaleString()}`).join(", ")})`
              : "";
            setDeleteNotice(
              result.workspace_removed
                ? `Deleted ${who} and its ${rows}${what}.`
                : `Deleted ${rows} from ${who}${what}. The workspace itself is still there.`,
            );
            setDeleting(null);
            load();
          }}
        />
      )}
    </div>
  );
}
