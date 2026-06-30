"use client";

import { useState, useEffect, useCallback } from "react";
import { Edit2, Trash2, RefreshCw } from "lucide-react";
import api from "@/lib/api";
import {
  type LoginIdRow, type SupplierOpt, INPUT, LABEL, apiError,
  ActiveBadge, UploadBox, ModalShell, Toolbar,
} from "@/components/userMaster/shared";

type AirlineOpt = { id: number; name: string; iata_code: string };
const LOB_OPTIONS = ["B2B", "B2C", "B2E", "MICE"];

export default function LoginIdPage() {
  const [rows, setRows] = useState<LoginIdRow[]>([]);
  const [suppliers, setSuppliers] = useState<SupplierOpt[]>([]);
  const [airlines, setAirlines] = useState<AirlineOpt[]>([]);
  const [loading, setLoading] = useState(true);
  const [apiErr, setApiErr] = useState("");
  const [search, setSearch] = useState("");
  const [modal, setModal] = useState<LoginIdRow | null | false>(false);

  const fetchRows = useCallback(async () => {
    setLoading(true); setApiErr("");
    try {
      const { data } = await api.get<LoginIdRow[]>("/login-ids/", { params: { search } });
      setRows(data);
    } catch (e) { setApiErr(apiError(e)); }
    finally { setLoading(false); }
  }, [search]);

  useEffect(() => { const t = setTimeout(fetchRows, 250); return () => clearTimeout(t); }, [fetchRows]);
  useEffect(() => {
    api.get<SupplierOpt[]>("/suppliers/", { params: { limit: 1000 } }).then(r => setSuppliers(r.data)).catch(() => setSuppliers([]));
    api.get<AirlineOpt[]>("/airlines/", { params: { limit: 1000 } }).then(r => setAirlines(r.data)).catch(() => setAirlines([]));
  }, []);

  const toggle = async (row: LoginIdRow) => {
    try {
      const { data } = await api.patch<LoginIdRow>(`/login-ids/${row.id}`, { is_active: !row.is_active });
      setRows(p => p.map(r => r.id === row.id ? data : r));
    } catch { alert("Update failed."); }
  };

  const del = async (id: number) => {
    if (!confirm("Delete this login ID? This cannot be undone.")) return;
    try { await api.delete(`/login-ids/${id}`); setRows(p => p.filter(r => r.id !== id)); }
    catch { alert("Delete failed."); }
  };

  return (
    <div className="space-y-4">
      <div>
        <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">User Master</p>
        <h1 className="text-xl font-bold text-gray-900">Login IDs / IATA</h1>
        <p className="text-xs text-gray-500 mt-0.5">Manage airline-portal login IDs / IATA codes and their vendor</p>
      </div>

      <Toolbar label="Login ID" count={rows.length} search={search} setSearch={setSearch}
        onAdd={() => setModal(null)} onRefresh={fetchRows} loading={loading} />

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr style={{ background: "#1e4d8c" }}>
                {["LOGIN ID / IATA", "AIRLINE", "AIRLINE CODE", "LOB", "VENDOR", "STATUS", "ACTIONS"].map(h => (
                  <th key={h} className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={7} className="px-4 py-12 text-center text-xs text-gray-400"><RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" />Loading…</td></tr>
              ) : apiErr ? (
                <tr><td colSpan={7} className="px-4 py-12 text-center text-xs text-red-400">{apiErr}</td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={7} className="px-4 py-12 text-center text-xs text-gray-400">No login IDs yet. Add one or upload an XLS.</td></tr>
              ) : rows.map((r, idx) => (
                <tr key={r.id} className={`border-b border-gray-50 hover:bg-sky-50/30 ${idx % 2 ? "bg-gray-50/30" : "bg-white"}`}>
                  <td className="px-3 py-2 text-[11px] font-semibold text-gray-800">{r.login_id}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{r.airline_name || "—"}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{r.airline_code || "—"}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{r.lob || "—"}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{r.vendor_name || "—"}</td>
                  <td className="px-3 py-2"><ActiveBadge active={r.is_active} onClick={() => toggle(r)} /></td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-1">
                      <button onClick={() => setModal(r)} className="p-1.5 hover:bg-blue-50 rounded-lg text-blue-400 hover:text-blue-600" title="Edit"><Edit2 className="w-3.5 h-3.5" /></button>
                      <button onClick={() => del(r.id)} className="p-1.5 hover:bg-red-50 rounded-lg text-red-400 hover:text-red-600" title="Delete"><Trash2 className="w-3.5 h-3.5" /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {modal !== false && (
        <LoginIdModal login={modal} suppliers={suppliers} airlines={airlines} onClose={() => setModal(false)} onSaved={() => { setModal(false); fetchRows(); }} />
      )}
    </div>
  );
}

function LoginIdModal({
  login, suppliers, airlines, onClose, onSaved,
}: {
  login: LoginIdRow | null;
  suppliers: SupplierOpt[];
  airlines: AirlineOpt[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = !!login;
  const [tab, setTab] = useState<"manual" | "xls">("manual");
  const [form, setForm] = useState({
    login_id: login?.login_id ?? "",
    airline_name: login?.airline_name ?? "",
    airline_code: login?.airline_code ?? "",
    lob: login?.lob ?? "",
    vendor_id: login?.vendor_id ?? null as number | null,
    is_active: login?.is_active ?? true,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const set = (k: keyof typeof form, v: string | number | boolean | null) => setForm(p => ({ ...p, [k]: v }));

  const save = async () => {
    if (!form.login_id.trim()) { setError("Login ID / IATA Code is required."); return; }
    setSaving(true); setError("");
    try {
      const body = { ...form, login_id: form.login_id.trim() };
      if (isEdit && login) await api.patch(`/login-ids/${login.id}`, body);
      else await api.post("/login-ids/", body);
      onSaved();
    } catch (e) { setError(apiError(e)); }
    finally { setSaving(false); }
  };

  return (
    <ModalShell title={isEdit ? "Edit Login ID" : "Add Login ID"} onClose={onClose}>
      {!isEdit && (
        <div className="flex border-b border-gray-100 mb-4 -mt-1">
          {(["manual", "xls"] as const).map(t => (
            <button key={t} onClick={() => setTab(t)}
              className={`flex-1 py-2.5 text-xs font-semibold ${tab === t ? "border-b-2 border-sky-500 text-sky-600" : "text-gray-400"}`}>
              {t === "manual" ? "Manual Entry" : "Upload XLS"}
            </button>
          ))}
        </div>
      )}

      {(isEdit || tab === "manual") ? (
        <div className="space-y-3">
          <div><label className={LABEL}>Login ID / IATA Code *</label>
            <input value={form.login_id} onChange={e => set("login_id", e.target.value)} placeholder="e.g. AI-DEL-001 or 14-3-XXXX" className={INPUT} /></div>
          <div className="grid grid-cols-2 gap-3">
            <div><label className={LABEL}>Airline Name</label>
              <select value={form.airline_name}
                onChange={e => {
                  const name = e.target.value;
                  const a = airlines.find(x => x.name === name);
                  setForm(p => ({ ...p, airline_name: name, airline_code: a ? a.iata_code : "" }));
                }}
                className={INPUT}>
                <option value="">— Select airline —</option>
                {form.airline_name && !airlines.some(a => a.name === form.airline_name) && (
                  <option value={form.airline_name}>{form.airline_name}</option>
                )}
                {airlines.map(a => <option key={a.id} value={a.name}>{a.name}</option>)}
              </select></div>
            <div><label className={LABEL}>Airline Code</label>
              <input value={form.airline_code} readOnly placeholder="Auto-filled"
                title="Auto-filled from the selected airline"
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-gray-100 text-gray-500 cursor-not-allowed focus:outline-none" /></div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div><label className={LABEL}>LoB</label>
              <select value={form.lob} onChange={e => set("lob", e.target.value)} className={INPUT}>
                <option value="">— Select LoB —</option>
                {form.lob && !LOB_OPTIONS.includes(form.lob) && (
                  <option value={form.lob}>{form.lob}</option>
                )}
                {LOB_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
              </select></div>
            <div><label className={LABEL}>Vendor</label>
              <select value={form.vendor_id ?? ""} onChange={e => set("vendor_id", e.target.value ? Number(e.target.value) : null)} className={INPUT}>
                <option value="">— Select vendor —</option>
                {suppliers.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select></div>
          </div>
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={form.is_active} onChange={e => set("is_active", e.target.checked)} className="w-4 h-4 rounded border-gray-300 text-sky-600 focus:ring-sky-400" />
            <span className="text-xs font-semibold text-gray-600">Active</span>
          </label>

          {error && <p className="text-[11px] text-red-500">{error}</p>}

          <div className="flex gap-3 pt-1">
            <button onClick={onClose} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
            <button onClick={save} disabled={saving} className="flex-1 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50" style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
              {saving ? "Saving…" : isEdit ? "Save Changes" : "Create Login ID"}
            </button>
          </div>
        </div>
      ) : (
        <UploadBox resource="login-ids" templateName="login_id_template.xlsx" columns="LOGIN_ID, AIRLINE_NAME, AIRLINE_CODE, LOB, VENDOR, ACTIVE" onDone={onSaved} />
      )}
    </ModalShell>
  );
}
