"use client";

// GST Configuration — Master Governance.
//
// The rules that say what GST is charged ON and at what rates, held as data so
// nothing downstream hardcodes a formula. Two categories, each subdivided along
// its own axis — abatement by what the TRIP is, normal by who the CUSTOMER is:
//
//   Abatement · Domestic       GST on a deemed  5% of basic fare  ┐ Rule 32(3),
//   Abatement · International  GST on a deemed 10% of basic fare  ┘ CGST Rules
//   Normal · Agency            GST on the agency's own service charge
//   Normal · Reseller          GST on the whole sale — fare + taxes + service charge
//
// Every rule is the same shape — `basis × taxable value % × rate %` — so the
// screen edits the same five numbers on each tab rather than four bespoke forms.
//
// CGST + SGST AND IGST ARE ALTERNATIVES, NOT ADDITIONS. Intra-state supply bills
// CGST + SGST (half each), inter-state bills IGST (the full rate). The preview
// below shows both columns side by side precisely so nobody reads the three rate
// fields as a 36% tax. The backend enforces it in services/gst_calc.py.
//
// A platform admin edits; everyone else reads. Master Governance owns tax rates,
// so unlike Suppliers / Airlines / IATA Commission there is no submit-for-approval
// queue — a tenant cannot propose one.

import { useState, useEffect, useCallback, useMemo } from "react";
import {
  RefreshCw, Save, Receipt, Percent, Calculator, Info,
  MapPin, Globe, AlertTriangle, Check,
} from "lucide-react";
import api from "@/lib/api";
import { canManageGlobalMasters } from "@/lib/rbac";
import { useAppSelector } from "@/store/hooks";
import { INPUT, LABEL, apiError } from "@/components/userMaster/shared";
import {
  SCHEMES, SUB_LABEL, BASIS_LABEL, shortBasis, rulesForScheme, rateMismatch,
  num, money, pct,
  type Basis, type GstConfig,
} from "@/lib/gstSchemes";

type SchemeKey = (typeof SCHEMES)[number]["key"];

// ── types ──────────────────────────────────────────────────────────────────

type Breakdown = {
  basis: Basis;
  basis_amount: number;
  taxable_value_pct: number;
  taxable_value: number;
  interstate: boolean;
  applied: "cgst_sgst" | "igst";
  effective_gst_pct: number;
  cgst: number;
  sgst: number;
  igst: number;
  total_gst: number;
};

type Preview = { formula: string; intrastate: Breakdown; interstate: Breakdown };

/** A one-line summary of a multi-rule scheme, naming whichever axis actually
 *  separates its rules.
 *
 *  Abatement's two rules share a basis and differ in the deemed slice, so the
 *  percentages are the story: "ABD 5% · ABI 10% of fare". Normal's differ in what
 *  is taxed at all, so the bases are: "NA Service Charge · NR Total Cost".
 *  Printing percentages for Normal would read "NA 100% · NR 100%", which says
 *  nothing. */
function summariseScheme(rules: GstConfig[]): string {
  const sharedBasis = rules.every(r => r.basis === rules[0].basis);
  return sharedBasis
    ? rules.map(r => `${r.code} ${pct(r.taxable_value_pct)}`).join(" · ") + " of fare"
    : rules.map(r => `${r.code} ${shortBasis(r.basis)}`).join(" · ");
}

const BASIS_HELP: Record<Basis, string> = {
  basic_fare: "The part of the air fare the airline pays commission on.",
  service_charge: "The agency's own service charge / service fee. The fare is not taxed.",
  total_cost: "The whole sale — fare plus taxes plus service charge.",
};

// SCHEMES / SUB_LABEL / BASIS_LABEL / rulesForScheme / rateMismatch and the
// number helpers live in @/lib/gstSchemes so this screen and My Profile cannot
// describe the same rules differently.

// ── the editable form for one rule ─────────────────────────────────────────

const emptyForm = {
  taxable_value_pct: "",
  cgst_pct: "",
  sgst_pct: "",
  igst_pct: "",
  sac_code: "",
  valid_from: "",
  valid_to: "",
  notes: "",
  is_active: true,
};
type FormState = typeof emptyForm;

const toForm = (c: GstConfig): FormState => ({
  taxable_value_pct: String(num(c.taxable_value_pct)),
  cgst_pct: String(num(c.cgst_pct)),
  sgst_pct: String(num(c.sgst_pct)),
  igst_pct: String(num(c.igst_pct)),
  sac_code: c.sac_code ?? "",
  valid_from: c.valid_from?.slice(0, 10) ?? "",
  valid_to: c.valid_to?.slice(0, 10) ?? "",
  notes: c.notes ?? "",
  is_active: c.is_active,
});

/** The formula sentence, rebuilt live from the form so it tracks unsaved edits.
 *  The saved version comes from the API (`config.formula`); this is what the
 *  numbers currently in the boxes would mean. */
function localFormula(basis: Basis, f: FormState) {
  const slice = num(f.taxable_value_pct);
  const base = BASIS_LABEL[basis];
  // A 100% slice is the identity — printing "× 100%" would only add noise.
  return slice === 100 ? base : `${base} × ${pct(slice)}`;
}

function RuleEditor({
  config, canEdit, onSaved,
}: {
  config: GstConfig;
  canEdit: boolean;
  onSaved: (updated: GstConfig) => void;
}) {
  const [form, setForm] = useState<FormState>(() => toForm(config));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [savedFlash, setSavedFlash] = useState(false);

  // Sample amounts for the calculator. Local to the screen — nothing is stored.
  const [sample, setSample] = useState({ basic_fare: "10000", taxes: "2000", service_charge: "500" });
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewErr, setPreviewErr] = useState("");

  // Switching tabs remounts this component via `key`, but a refetch of the same
  // tab does not — so re-sync when the row itself changes.
  useEffect(() => { setForm(toForm(config)); }, [config]);

  const set = (k: keyof FormState, v: string | boolean) => setForm(p => ({ ...p, [k]: v }));

  const body = useMemo(() => ({
    taxable_value_pct: num(form.taxable_value_pct),
    cgst_pct: num(form.cgst_pct),
    sgst_pct: num(form.sgst_pct),
    igst_pct: num(form.igst_pct),
    sac_code: form.sac_code.trim() || null,
    valid_from: form.valid_from || null,
    valid_to: form.valid_to || null,
    notes: form.notes.trim() || null,
    is_active: form.is_active,
  }), [form]);

  const dirty = useMemo(() => JSON.stringify(toForm(config)) !== JSON.stringify(form), [config, form]);

  // The preview is computed by the SAME service that will bill a real ticket, so
  // the screen can never drift from the arithmetic. It runs against the SAVED row
  // — the banner below says so, since the boxes may hold unsaved edits.
  const runPreview = useCallback(async () => {
    setPreviewErr("");
    try {
      const { data } = await api.post<Preview>(`/gst-configurations/${config.id}/preview`, {
        basic_fare: num(sample.basic_fare),
        taxes: num(sample.taxes),
        service_charge: num(sample.service_charge),
      });
      setPreview(data);
    } catch (e) { setPreviewErr(apiError(e)); setPreview(null); }
  }, [config.id, sample]);

  useEffect(() => { const t = setTimeout(runPreview, 300); return () => clearTimeout(t); }, [runPreview]);

  const save = async () => {
    // The three rate fields are two alternatives, so validate them as such:
    // CGST and SGST are halves of the same intra-state rate and must match, and
    // together they have to equal IGST or the same sale is taxed differently by
    // nothing more than the customer's address.
    const c = num(form.cgst_pct), s = num(form.sgst_pct), i = num(form.igst_pct);
    if (c !== s) { setError("CGST and SGST must be equal — they are the two halves of one intra-state rate."); return; }
    if (Math.abs(c + s - i) > 0.0001) {
      setError(`CGST + SGST (${pct(c + s)}) must equal IGST (${pct(i)}) — intra-state and inter-state supply carry the same total tax.`);
      return;
    }
    if (num(form.taxable_value_pct) <= 0) { setError("Taxable value % must be greater than zero."); return; }
    if (form.valid_from && form.valid_to && form.valid_from > form.valid_to) {
      setError("Valid From cannot be after Valid To."); return;
    }
    setSaving(true); setError("");
    try {
      const { data } = await api.patch<GstConfig>(`/gst-configurations/${config.id}`, body);
      onSaved(data);
      setSavedFlash(true);
      setTimeout(() => setSavedFlash(false), 2000);
    } catch (e) { setError(apiError(e)); }
    finally { setSaving(false); }
  };

  const formulaBase = localFormula(config.basis, form);

  return (
    <div className="space-y-4">
      {/* ── what this rule charges on ─────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Receipt className="w-4 h-4 text-sky-500" />
            <p className="text-xs font-semibold text-gray-700">{config.name}</p>
            <span className="px-1.5 py-0.5 rounded bg-gray-100 text-[10px] font-bold text-gray-500 tracking-wider">
              {config.code}
            </span>
          </div>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox" checked={form.is_active} disabled={!canEdit}
              onChange={e => set("is_active", e.target.checked)}
              className="w-4 h-4 rounded border-gray-300 text-sky-600 focus:ring-sky-400 disabled:opacity-50"
            />
            <span className="text-[11px] font-semibold text-gray-600">Active</span>
          </label>
        </div>

        <div className="px-4 py-4 space-y-4">
          {/* The basis is what makes this rule different from the other two, so
              it is stated rather than editable — changing it would turn this row
              into one of the others. */}
          <div className="flex items-start gap-3 bg-sky-50/60 border border-sky-100 rounded-lg px-3 py-2.5">
            <Info className="w-3.5 h-3.5 text-sky-500 mt-0.5 shrink-0" />
            <div>
              <p className="text-[11px] font-semibold text-sky-900">
                Charged on: {BASIS_LABEL[config.basis]}
              </p>
              <p className="text-[11px] text-sky-700/80 mt-0.5">{BASIS_HELP[config.basis]}</p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
            <div>
              <label className={LABEL}>Taxable Value %</label>
              <input
                type="number" step="any" value={form.taxable_value_pct} disabled={!canEdit}
                onChange={e => set("taxable_value_pct", e.target.value)}
                className={INPUT} placeholder="e.g. 5"
              />
              <p className="text-[10px] text-gray-400 mt-1">
                The slice of {BASIS_LABEL[config.basis].split(" (")[0]} that is taxable.
              </p>
            </div>
            {([
              ["cgst_pct", "CGST %", "Intra-state, with SGST"],
              ["sgst_pct", "SGST %", "Intra-state, with CGST"],
              ["igst_pct", "IGST %", "Inter-state, on its own"],
            ] as const).map(([key, label, help]) => (
              <div key={key}>
                <label className={LABEL}>{label}</label>
                <input
                  type="number" step="any" value={form[key]} disabled={!canEdit}
                  onChange={e => set(key, e.target.value)}
                  className={INPUT} placeholder="e.g. 9"
                />
                <p className="text-[10px] text-gray-400 mt-1">{help}</p>
              </div>
            ))}
          </div>

          {/* The rule as a sentence, rebuilt from whatever is in the boxes now. */}
          <div className="rounded-lg border border-gray-200 bg-gray-50/70 px-3 py-2.5">
            <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-1.5">
              Resulting formula{dirty && <span className="text-amber-600 normal-case tracking-normal"> · unsaved</span>}
            </p>
            <div className="space-y-1 font-mono text-[11px] text-gray-700">
              <p>CGST = {formulaBase} × {pct(form.cgst_pct)}</p>
              <p>SGST = {formulaBase} × {pct(form.sgst_pct)}</p>
              <p>IGST = {formulaBase} × {pct(form.igst_pct)}</p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div>
              <label className={LABEL}>SAC Code</label>
              <input value={form.sac_code} disabled={!canEdit}
                onChange={e => set("sac_code", e.target.value)}
                placeholder="e.g. 998551" className={INPUT} />
            </div>
            <div>
              <label className={LABEL}>Valid From</label>
              <input type="date" value={form.valid_from} disabled={!canEdit}
                onChange={e => set("valid_from", e.target.value)} className={INPUT} />
            </div>
            <div>
              <label className={LABEL}>Valid To</label>
              <input type="date" value={form.valid_to} disabled={!canEdit}
                onChange={e => set("valid_to", e.target.value)} className={INPUT} />
            </div>
          </div>

          <div>
            <label className={LABEL}>Notes</label>
            <textarea rows={2} value={form.notes} disabled={!canEdit}
              onChange={e => set("notes", e.target.value)}
              placeholder="Why this rule exists, or the rule it comes from…"
              className={`${INPUT} resize-none`} />
          </div>

          {error && (
            <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              <AlertTriangle className="w-3.5 h-3.5 text-red-500 mt-0.5 shrink-0" />
              <p className="text-[11px] text-red-600">{error}</p>
            </div>
          )}

          {canEdit && (
            <div className="flex items-center gap-3 pt-1">
              <button
                onClick={save} disabled={saving || !dirty}
                className="flex items-center gap-1.5 text-white rounded-lg px-4 py-2 text-sm font-semibold disabled:opacity-50"
                style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}
              >
                {savedFlash ? <Check className="w-3.5 h-3.5" /> : <Save className="w-3.5 h-3.5" />}
                {saving ? "Saving…" : savedFlash ? "Saved" : "Save Changes"}
              </button>
              {dirty && !saving && (
                <button
                  onClick={() => { setForm(toForm(config)); setError(""); }}
                  className="text-xs text-gray-500 hover:text-gray-700 underline underline-offset-2"
                >
                  Discard changes
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── the calculator ────────────────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-2">
          <Calculator className="w-4 h-4 text-violet-500" />
          <p className="text-xs font-semibold text-gray-700">Check it against an example</p>
          {dirty && (
            <span className="ml-auto text-[10px] font-semibold text-amber-600">
              Showing the saved rule — save to preview your edits
            </span>
          )}
        </div>

        <div className="px-4 py-4 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {([
              ["basic_fare", "Basic Fare"],
              ["taxes", "Taxes"],
              ["service_charge", "Service Charge"],
            ] as const).map(([key, label]) => (
              <div key={key}>
                <label className={LABEL}>{label}</label>
                <input type="number" step="any" value={sample[key]}
                  onChange={e => setSample(p => ({ ...p, [key]: e.target.value }))}
                  className={INPUT} />
              </div>
            ))}
          </div>

          {previewErr && <p className="text-[11px] text-red-500">{previewErr}</p>}

          {preview && (
            <>
              <div className="grid grid-cols-2 gap-3 text-[11px]">
                <div className="rounded-lg border border-gray-200 px-3 py-2 bg-gray-50/70">
                  <p className="text-gray-400 uppercase tracking-widest text-[10px] font-semibold">Amount charged on</p>
                  <p className="text-sm font-bold text-gray-800 mt-0.5">₹ {money(preview.intrastate.basis_amount)}</p>
                  <p className="text-gray-500 mt-0.5">{BASIS_LABEL[preview.intrastate.basis]}</p>
                </div>
                <div className="rounded-lg border border-gray-200 px-3 py-2 bg-gray-50/70">
                  <p className="text-gray-400 uppercase tracking-widest text-[10px] font-semibold">Taxable value</p>
                  <p className="text-sm font-bold text-gray-800 mt-0.5">₹ {money(preview.intrastate.taxable_value)}</p>
                  <p className="text-gray-500 mt-0.5">
                    {pct(preview.intrastate.taxable_value_pct)} of the amount above
                  </p>
                </div>
              </div>

              {/* Two columns, never one blended figure. This layout IS the
                  explanation that only one of them is ever billed. */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {([
                  { b: preview.intrastate, title: "Intra-state supply", sub: "Same state — CGST + SGST", Icon: MapPin, tone: "emerald" },
                  { b: preview.interstate, title: "Inter-state supply", sub: "Different state — IGST only", Icon: Globe, tone: "indigo" },
                ] as const).map(({ b, title, sub, Icon, tone }) => (
                  <div key={title} className={`rounded-xl border p-3 ${
                    tone === "emerald" ? "border-emerald-200 bg-emerald-50/40" : "border-indigo-200 bg-indigo-50/40"
                  }`}>
                    <div className="flex items-center gap-1.5 mb-2">
                      <Icon className={`w-3.5 h-3.5 ${tone === "emerald" ? "text-emerald-600" : "text-indigo-600"}`} />
                      <p className="text-[11px] font-bold text-gray-800">{title}</p>
                    </div>
                    <p className="text-[10px] text-gray-500 mb-2">{sub}</p>
                    {([["CGST", b.cgst], ["SGST", b.sgst], ["IGST", b.igst]] as const).map(([label, value]) => (
                      <div key={label} className="flex justify-between py-0.5 text-[11px]">
                        <span className={value === 0 ? "text-gray-300" : "text-gray-600"}>{label}</span>
                        <span className={value === 0 ? "text-gray-300" : "font-semibold text-gray-800"}>
                          {value === 0 ? "—" : `₹ ${money(value)}`}
                        </span>
                      </div>
                    ))}
                    <div className="flex justify-between pt-1.5 mt-1 border-t border-gray-200/70 text-[11px]">
                      <span className="font-semibold text-gray-700">Total GST</span>
                      <span className="font-bold text-gray-900">₹ {money(b.total_gst)}</span>
                    </div>
                    <p className="text-[10px] text-gray-400 mt-1">Effective {pct(b.effective_gst_pct)}</p>
                  </div>
                ))}
              </div>

              <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
                <AlertTriangle className="w-3.5 h-3.5 text-amber-500 mt-0.5 shrink-0" />
                <p className="text-[11px] text-amber-800">
                  Only <strong>one</strong> of these two columns is ever billed on a given transaction —
                  whichever the place of supply decides. CGST + SGST and IGST are alternatives, never added together.
                </p>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ── page ───────────────────────────────────────────────────────────────────

export default function GstConfigurationPage() {
  const user = useAppSelector(s => s.auth.user);
  const canEdit = canManageGlobalMasters(user?.role);

  const [rows, setRows] = useState<GstConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [apiErr, setApiErr] = useState("");
  const [tab, setTab] = useState<SchemeKey>("abatement");

  const fetchRows = useCallback(async () => {
    setLoading(true); setApiErr("");
    try {
      const { data } = await api.get<GstConfig[]>("/gst-configurations/");
      setRows(data);
    } catch (e) { setApiErr(apiError(e)); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchRows(); }, [fetchRows]);

  const rulesFor = useCallback(
    (scheme: (typeof SCHEMES)[number]) => rulesForScheme(scheme, rows),
    [rows],
  );

  const spec = SCHEMES.find(s => s.key === tab)!;
  const current = rulesFor(spec);
  // Gate the multi-rule affordances on how many rules the scheme HAS, not how
  // many came back. Deactivating ABI must not let ABD quietly pose as the whole
  // of abatement — a reader would conclude it is a single 5% rule.
  const multiRule = spec.subs.length > 1;
  const missingCount = spec.subs.length - current.length;

  const activeCount = rows.filter(r => r.is_active).length;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">Master Governance</p>
          <h1 className="text-xl font-bold text-gray-900">GST Configuration</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            {rows.length} rule{rows.length !== 1 ? "s" : ""} · {activeCount} active
          </p>
        </div>
        <button onClick={fetchRows} disabled={loading}
          className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-600 px-3 py-2 rounded-lg text-xs font-medium hover:bg-gray-50 disabled:opacity-50">
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {SCHEMES.map(scheme => {
          const { key, label } = scheme;
          const ruleRows = rulesFor(scheme);
          return (
            <button key={key} onClick={() => setTab(key)}
              className={`bg-white rounded-xl border px-3 py-2 flex items-center gap-3 shadow-sm text-left transition-colors ${
                tab === key ? "border-sky-400 ring-1 ring-sky-200" : "border-gray-100 hover:border-gray-200"
              }`}>
              <div className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${
                tab === key ? "text-sky-600 bg-sky-50" : "text-gray-400 bg-gray-50"
              }`}>
                <Percent className="w-4 h-4" />
              </div>
              <div className="min-w-0">
                <p className="text-[11px] font-bold text-gray-900 leading-none truncate">{label}</p>
                <p className="text-[11px] text-gray-400 mt-1 truncate">
                  {/* Abatement carries two rules and the deemed % is what tells
                      them apart, so summarise both rather than making the reader
                      open the tab. A single-rule scheme names its basis instead.
                      Codes come from the live rows, never a literal — renaming
                      one must not leave a stale label beside the true value. */}
                  {ruleRows.length === 0
                    ? "not configured"
                    : scheme.subs.length > 1
                      ? summariseScheme(ruleRows) +
                        (ruleRows.length < scheme.subs.length ? " · incomplete" : "")
                      : `${ruleRows[0].code} · on ${shortBasis(ruleRows[0].basis)}`}
                </p>
              </div>
            </button>
          );
        })}
      </div>

      <p className="text-xs text-gray-500">
        What GST is charged on, and at what rates. Every rule is{" "}
        <span className="font-mono text-[11px] text-gray-600">basis × taxable value % × rate %</span> —
        so the formulas live here as data rather than in code.
        {!canEdit && " These rates are maintained by the platform team."}
      </p>

      {/* One level. The three schemes are the only real choices — a sector is a
          property of the ticket, so Abatement's two rules live inside its tab
          rather than beside it as a second decision. */}
      <div className="flex gap-1 bg-gray-100 rounded-xl p-1 w-fit">
        {SCHEMES.map(({ key, label }) => (
          <button key={key} onClick={() => setTab(key)}
            className={`px-4 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              tab === key ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-700"
            }`}>
            {label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm px-4 py-16 text-center">
          <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" />
          <p className="text-xs text-gray-400">Loading…</p>
        </div>
      ) : apiErr ? (
        <div className="bg-white rounded-xl border border-red-100 shadow-sm px-4 py-16 text-center">
          <p className="text-xs text-red-500">{apiErr}</p>
        </div>
      ) : current.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm px-4 py-16 text-center">
          <p className="text-sm font-medium text-gray-600">This scheme is not configured</p>
          <p className="text-xs text-gray-400 mt-1 max-w-md mx-auto leading-relaxed">
            No GST configuration row exists for {spec.label}. The four defaults are
            seeded by the <span className="font-mono">gst_config_01</span> and{" "}
            <span className="font-mono">gst_config_02</span> migrations.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {/* Each scheme holds two rules, so it stacks two editors. Each saves on
              its own: two rows means two PATCHes, and a shared button would have
              to claim "Saved" over a half-applied change when the second failed. */}
          {multiRule && (
            <div className="flex items-start gap-2 bg-sky-50/60 border border-sky-100 rounded-lg px-3 py-2.5">
              <Info className="w-3.5 h-3.5 text-sky-500 mt-0.5 shrink-0" />
              <p className="text-[11px] text-sky-800">{spec.note}</p>
            </div>
          )}

          {/* A scheme missing one of its rules is not a smaller scheme — it is a
              broken one. Say so, or the survivor reads as the whole thing. */}
          {missingCount > 0 && (
            <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2.5">
              <AlertTriangle className="w-3.5 h-3.5 text-amber-500 mt-0.5 shrink-0" />
              <p className="text-[11px] text-amber-800">
                {missingCount} of this scheme&apos;s {spec.subs.length} rules{" "}
                {missingCount === 1 ? "is" : "are"} missing or inactive:{" "}
                <strong>
                  {spec.subs
                    .filter(sub => !current.some(r => r.sub_category === sub))
                    .map(sub => SUB_LABEL[sub])
                    .join(", ")}
                </strong>
                . No GST can be calculated for those sectors until{" "}
                {missingCount === 1 ? "it is" : "they are"} configured.
              </p>
            </div>
          )}

          {/* The two abatement rules differ only in the deemed slice; the tax
              rates themselves should match. Nothing in the schema enforces it,
              so having both on one screen is the chance to notice. */}
          {rateMismatch(current) && (
            <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2.5">
              <AlertTriangle className="w-3.5 h-3.5 text-amber-500 mt-0.5 shrink-0" />
              <p className="text-[11px] text-amber-800">
                These rules carry <strong>different CGST / SGST / IGST rates</strong>. Abatement
                differs by sector only in the deemed slice of the fare — the rates applied to it
                are normally identical. Check this is deliberate.
              </p>
            </div>
          )}

          {current.map(config => (
            <div key={config.id} className="space-y-2">
              {/* Only worth naming the rule when the scheme holds more than one. */}
              {multiRule && (
                <div className="flex items-baseline gap-2 px-1">
                  <h2 className="text-xs font-bold text-gray-700">
                    {config.sub_category ? SUB_LABEL[config.sub_category] : config.name}
                  </h2>
                  <span className="text-[10px] text-gray-400">
                    {/* A 100% slice is the identity — "100% of service charge" is
                        noise, the same reason the formula line omits it. */}
                    {config.code} ·{" "}
                    {num(config.taxable_value_pct) === 100
                      ? `on ${shortBasis(config.basis)}`
                      : `${pct(config.taxable_value_pct)} of ${shortBasis(config.basis).toLowerCase()}`}
                  </span>
                </div>
              )}
              <RuleEditor
                config={config}
                canEdit={canEdit}
                onSaved={updated => setRows(p => p.map(r => (r.id === updated.id ? updated : r)))}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
