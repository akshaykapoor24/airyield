"use client";

// What the workspace's GST scheme actually does, in numbers.
//
// The dropdown beside this component records an ELECTION — abatement, normal
// agency or normal reseller. That word alone tells nobody what they will be
// taxed, so this shows the rules behind it: the formula, and a worked example on
// amounts the reader can change.
//
// Every figure comes from POST /gst-configurations/{id}/preview, i.e. from the
// same services/gst_calc.compute_gst that would bill a real ticket. Nothing is
// recomputed in the browser, so this panel cannot drift from the arithmetic.
//
// Abatement renders TWO blocks — 5% domestic and 10% international — because it
// is one scheme spanning two rules, picked per ticket by sector rather than by
// another choice the user makes.
//
// Read-only. Changing the scheme is the dropdown's job; this only explains it.

import { useState, useEffect, useCallback } from "react";
import { Calculator, MapPin, Globe, AlertTriangle, RefreshCw } from "lucide-react";
import api from "@/lib/api";
import { LABEL, apiError } from "@/components/userMaster/shared";
import {
  schemeByKey, SUB_LABEL, shortBasis, rulesForScheme,
  num, money, pct,
  type GstConfig,
} from "@/lib/gstSchemes";

type Breakdown = {
  basis_amount: number;
  taxable_value: number;
  cgst: number;
  sgst: number;
  igst: number;
  total_gst: number;
  effective_gst_pct: number;
};

type Preview = { formula: string; intrastate: Breakdown; interstate: Breakdown };

const SMALL_INPUT =
  "w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-sky-400 bg-gray-50";

/** One rule: its formula, and the two place-of-supply outcomes side by side. */
function RuleBlock({
  config, sample, showTitle,
}: {
  config: GstConfig;
  sample: { basic_fare: string; taxes: string; service_charge: string };
  showTitle: boolean;
}) {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [err, setErr] = useState("");

  // Debounced so typing into the sample boxes does not fire a request per
  // keystroke, and guarded so a slow reply cannot overwrite a newer one — the
  // amounts change while requests are in flight, and a stale answer here is a
  // wrong tax figure sitting under the right inputs.
  useEffect(() => {
    let cancelled = false;
    const t = setTimeout(async () => {
      try {
        const { data } = await api.post<Preview>(`/gst-configurations/${config.id}/preview`, {
          basic_fare: num(sample.basic_fare),
          taxes: num(sample.taxes),
          service_charge: num(sample.service_charge),
        });
        if (!cancelled) { setPreview(data); setErr(""); }
      } catch (e) {
        if (!cancelled) { setErr(apiError(e)); setPreview(null); }
      }
    }, 300);
    return () => { cancelled = true; clearTimeout(t); };
  }, [config.id, sample]);

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3 space-y-2.5">
      {showTitle && (
        <div className="flex items-baseline gap-2">
          <p className="text-[11px] font-bold text-gray-800">
            {config.sub_category ? SUB_LABEL[config.sub_category] : config.name}
          </p>
          <span className="text-[10px] text-gray-400">
            {/* A 100% slice is the identity, so name the basis instead. */}
            {config.code} ·{" "}
            {num(config.taxable_value_pct) === 100
              ? `on ${shortBasis(config.basis)}`
              : `${pct(config.taxable_value_pct)} of ${shortBasis(config.basis).toLowerCase()}`}
          </span>
        </div>
      )}

      {/* The server-rendered sentence, so the wording matches the master screen. */}
      {config.formula && (
        <p className="font-mono text-[10px] text-gray-600 leading-relaxed break-words">
          {config.formula}
        </p>
      )}

      {err && <p className="text-[11px] text-red-500">{err}</p>}

      {preview && (
        <>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-gray-500">
            <span>Charged on <strong className="text-gray-700">₹ {money(preview.intrastate.basis_amount)}</strong></span>
            <span>Taxable value <strong className="text-gray-700">₹ {money(preview.intrastate.taxable_value)}</strong></span>
          </div>

          {/* Two columns, never one blended figure — only one is ever billed. */}
          <div className="grid grid-cols-2 gap-2">
            {([
              { b: preview.intrastate, title: "Same state", sub: "CGST + SGST", Icon: MapPin, tone: "emerald" },
              { b: preview.interstate, title: "Other state", sub: "IGST only", Icon: Globe, tone: "indigo" },
            ] as const).map(({ b, title, sub, Icon, tone }) => (
              <div key={title} className={`rounded-lg border p-2 ${
                tone === "emerald" ? "border-emerald-200 bg-emerald-50/40" : "border-indigo-200 bg-indigo-50/40"
              }`}>
                <div className="flex items-center gap-1 mb-1">
                  <Icon className={`w-3 h-3 ${tone === "emerald" ? "text-emerald-600" : "text-indigo-600"}`} />
                  <p className="text-[10px] font-bold text-gray-800">{title}</p>
                </div>
                <p className="text-[9px] text-gray-500 mb-1">{sub}</p>
                {([["CGST", b.cgst], ["SGST", b.sgst], ["IGST", b.igst]] as const).map(([label, value]) => (
                  <div key={label} className="flex justify-between text-[10px] py-0.5">
                    <span className={value === 0 ? "text-gray-300" : "text-gray-600"}>{label}</span>
                    <span className={value === 0 ? "text-gray-300" : "font-semibold text-gray-800"}>
                      {value === 0 ? "—" : `₹ ${money(value)}`}
                    </span>
                  </div>
                ))}
                <div className="flex justify-between pt-1 mt-0.5 border-t border-gray-200/70 text-[10px]">
                  <span className="font-semibold text-gray-700">Total</span>
                  <span className="font-bold text-gray-900">₹ {money(b.total_gst)}</span>
                </div>
                <p className="text-[9px] text-gray-400 mt-0.5">Effective {pct(b.effective_gst_pct)}</p>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

export default function GstSchemePreview({ scheme }: { scheme: string }) {
  const [rows, setRows] = useState<GstConfig[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [sample, setSample] = useState({ basic_fare: "10000", taxes: "2000", service_charge: "500" });

  // Fetched ONCE, not per scheme: the response is the whole rule set and does
  // not depend on which scheme is selected, so keying this on `scheme` would
  // refetch identical data every time the dropdown moved.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true); setErr("");
      try {
        // Reads are open to any authenticated user, so no new endpoint is needed
        // for a tenant to see the platform's rules.
        const { data } = await api.get<GstConfig[]>("/gst-configurations/", {
          params: { active_only: true },
        });
        if (!cancelled) setRows(data);
      } catch (e) { if (!cancelled) setErr(apiError(e)); }
      finally { if (!cancelled) setLoading(false); }
    })();
    return () => { cancelled = true; };
  }, []);

  // Nothing elected — the dropdown above says everything there is to say.
  if (!scheme) return null;

  const spec = schemeByKey(scheme);
  // An unrecognised saved slug: say so rather than rendering a blank panel.
  if (!spec) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5">
        <p className="text-[11px] text-amber-800">
          <strong>{scheme}</strong> is not a GST scheme this version recognises.
          Pick one from the list above.
        </p>
      </div>
    );
  }

  // Ordered by the scheme's own `subs`, so Abatement always reads Domestic first.
  const rules = rulesForScheme(spec, rows);
  // Gate on how many rules the scheme HAS, not how many came back — otherwise a
  // deactivated International rule lets Domestic pose as the whole of abatement.
  const multiRule = spec.subs.length > 1;
  const missing = spec.subs.filter(sub => !rules.some(r => r.sub_category === sub));

  return (
    <div className="rounded-xl border border-gray-200 bg-gray-50/60 p-3 space-y-3">
      <div className="flex items-center gap-1.5">
        <Calculator className="w-3.5 h-3.5 text-violet-500" />
        <p className="text-[11px] font-semibold text-gray-700">How this is calculated</p>
      </div>

      {loading ? (
        <p className="flex items-center gap-1.5 text-[11px] text-gray-400">
          <RefreshCw className="w-3 h-3 animate-spin" /> Loading the rules…
        </p>
      ) : err ? (
        <p className="text-[11px] text-red-500">{err}</p>
      ) : rules.length === 0 ? (
        <p className="text-[11px] text-gray-500">
          The platform has not configured a rule for this scheme yet, so no
          calculation can be shown.
        </p>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-2">
            {([
              ["basic_fare", "Basic Fare"],
              ["taxes", "Taxes"],
              ["service_charge", "Service Charge"],
            ] as const).map(([key, label]) => (
              <div key={key}>
                <label className={LABEL}>{label}</label>
                <input type="number" step="any" value={sample[key]}
                  onChange={e => setSample(p => ({ ...p, [key]: e.target.value }))}
                  className={SMALL_INPUT} />
              </div>
            ))}
          </div>

          <div className="space-y-2">
            {rules.map(config => (
              <RuleBlock key={config.id} config={config} sample={sample}
                showTitle={multiRule} />
            ))}
          </div>

          {/* A scheme short of one of its rules is broken, not smaller. Without
              this the survivor reads as the whole scheme. */}
          {missing.length > 0 && (
            <div className="flex items-start gap-1.5 rounded-lg border border-amber-200 bg-amber-50 px-2 py-1.5">
              <AlertTriangle className="w-3 h-3 text-amber-500 mt-0.5 shrink-0" />
              <p className="text-[10px] text-amber-800 leading-relaxed">
                <strong>{missing.map(s => SUB_LABEL[s]).join(", ")}</strong>{" "}
                {missing.length === 1 ? "is" : "are"} not currently configured, so no
                calculation can be shown for {missing.length === 1 ? "that sector" : "those sectors"}.
                Contact the platform team.
              </p>
            </div>
          )}

          <div className="flex items-start gap-1.5">
            <AlertTriangle className="w-3 h-3 text-amber-500 mt-0.5 shrink-0" />
            <p className="text-[10px] text-amber-800 leading-relaxed">
              Only <strong>one</strong> column is billed on a given sale — whichever the place of
              supply decides. CGST + SGST and IGST are alternatives, never added together.
              {/* And which of the scheme's two rules applies is likewise not a choice
                  made here — say what actually decides it, per scheme. */}
              {multiRule && ` ${spec.note}`}
            </p>
          </div>

          <p className="text-[10px] text-gray-400">
            Rates are maintained by the platform team. Electing a scheme here records
            how this workspace bills; it does not change any rate.
          </p>
        </>
      )}
    </div>
  );
}
