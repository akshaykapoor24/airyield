"use client";

import { useEffect, useState } from "react";
import { X, CheckCircle2, XCircle, MinusCircle } from "lucide-react";
import api from "@/lib/api";
import { inr, SKIPPED_LABEL, STAT_LABEL } from "./types";

type Step = { step: string; passed: boolean; ticket_value: string; deal_value: string; detail: string };
type Plb = {
  plb_key: string;
  steps: Step[];
  incentive_breakdown: Record<string, unknown> | null;
  plb_overall_match: boolean;
};
type DealDiag = {
  deal_id: number;
  deal_no: string;
  deal_name: string;
  deal_type: string;
  valid_from: string | null;
  valid_to: string | null;
  deal_validity_step: Step;
  plbs: Plb[];
  overall_match: boolean;
  best_incentive: number | null;
};
type Diagnosis = {
  row_id: number;
  document_number: string | null;
  transaction_type: string | null;
  raw_airline_code: string | null;
  airline_resolved: string | null;
  issue_date: string | null;
  stat: string | null;
  segment_type: string | null;
  fare_amount: number | null;
  sell_tax_yq: number | null;
  sale_yr: number | null;
  tour_code: string | null;
  skipped_criteria: string[];
  // From the TGQ HMPR counterpart, when one was found.
  sector: string | null;
  booking_class: string | null;
  travel_date: string | null;
  travel_date_source: string | null;
  leg_count: number | null;
  enrichment_source: string | null;
  enrichment_ref: string | null;
  commission_status: string;
  commission_reason: string | null;
  deals: DealDiag[];
  total_deals_checked: number;
  matched_count: number;
  note?: string;
};

function StepIcon({ step }: { step: Step }) {
  // A step whose ticket value reads "not printed" was skipped, not proved.
  if (step.ticket_value === "not printed") return <MinusCircle className="w-3.5 h-3.5 text-slate-400 shrink-0" />;
  return step.passed
    ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 shrink-0" />
    : <XCircle className="w-3.5 h-3.5 text-red-500 shrink-0" />;
}

export default function CommissionDiagnosisModal({
  rowId, document, onClose,
}: { rowId: number; document: string | null; onClose: () => void }) {
  const [data, setData] = useState<Diagnosis | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const { data } = await api.get<Diagnosis>(`/bsp-commission/rows/${rowId}/match-diagnosis`);
        if (alive) setData(data);
      } catch {
        if (alive) setError("Could not load the match diagnosis.");
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [rowId]);

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 overflow-y-auto">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-4xl my-8">
        <div className="flex items-center justify-between px-5 py-3 border-b border-slate-200">
          <div>
            <h2 className="text-sm font-semibold text-slate-800">Why this row matched (or didn&apos;t)</h2>
            <p className="text-[11px] text-slate-400 mt-0.5">Document {document || rowId}</p>
          </div>
          <button onClick={onClose} className="p-1 text-slate-400 hover:text-slate-700"><X className="w-4 h-4" /></button>
        </div>

        <div className="p-5">
          {loading ? (
            <p className="text-sm text-slate-400 py-8 text-center">Loading…</p>
          ) : error ? (
            <p className="text-sm text-red-500 py-8 text-center">{error}</p>
          ) : !data ? null : (
            <>
              {/* What the statement gave the engine */}
              <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 mb-4">
                <p className="text-[11px] uppercase tracking-wide text-slate-400 font-semibold mb-2">
                  {data.enrichment_source ? "From the BSP statement + TGQ HMPR" : "From the BSP statement"}
                </p>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-x-4 gap-y-2 text-xs">
                  <Field label="Airline code" value={data.raw_airline_code} />
                  <Field label="Resolved airline" value={data.airline_resolved ?? "not in master"} />
                  <Field label="Issue date" value={data.issue_date} />
                  <Field label="TRNC" value={data.transaction_type} />
                  <Field label="STAT" value={data.stat ? `${data.stat} — ${STAT_LABEL[data.stat] ?? "?"}` : null} />
                  <Field label="Fare" value={inr(data.fare_amount)} />
                  <Field label="YQ" value={inr(data.sell_tax_yq)} />
                  <Field label="YR" value={inr(data.sale_yr)} />
                  {data.tour_code && <Field label="Tour code" value={data.tour_code} />}
                  {data.sector && <Field label="Sector" value={data.sector} />}
                  {data.booking_class && <Field label="Class" value={data.booking_class} />}
                  {data.travel_date && (
                    <Field
                      label="Travel date"
                      value={data.travel_date + (data.travel_date_source === "inferred" ? " (year inferred)" : "")}
                    />
                  )}
                </div>
                {data.enrichment_source && (
                  <p className="text-[11px] text-sky-700 mt-2.5 pt-2.5 border-t border-slate-200">
                    Cabin class, sector and travel date came from the TGQ HMPR statement
                    ({data.leg_count ?? 1} {(data.leg_count ?? 1) === 1 ? "sector" : "sectors"} folded
                    into one journey), so the deal criteria that depend on them were evaluated.
                  </p>
                )}
                {data.skipped_criteria?.length > 0 && (
                  <p className="text-[11px] text-slate-500 mt-2.5 pt-2.5 border-t border-slate-200">
                    <span className="font-semibold">Not checked:</span>{" "}
                    {data.skipped_criteria.map((c) => SKIPPED_LABEL[c] ?? c).join(", ")} — the BSP
                    statement does not print them and no TGQ HMPR ticket matched this document, so
                    those deal criteria were skipped rather than guessed.
                  </p>
                )}
              </div>

              {data.note && <p className="text-xs text-orange-600 mb-4">{data.note}</p>}
              {data.commission_reason && (
                <p className="text-xs text-slate-600 mb-4">
                  <span className="font-semibold">Result:</span> {data.commission_reason}
                </p>
              )}

              <p className="text-[11px] text-slate-400 mb-2">
                {data.total_deals_checked} airline deal{data.total_deals_checked === 1 ? "" : "s"} checked,
                {" "}{data.matched_count} matched.
              </p>

              <div className="space-y-2">
                {data.deals.map((d) => (
                  <div key={d.deal_id} className="border border-slate-200 rounded-lg overflow-hidden">
                    <button
                      onClick={() => setOpen(open === d.deal_id ? null : d.deal_id)}
                      className="w-full flex items-center justify-between px-3 py-2 hover:bg-slate-50 text-left"
                    >
                      <span className="flex items-center gap-2 text-xs">
                        {d.overall_match
                          ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
                          : <XCircle className="w-3.5 h-3.5 text-red-400" />}
                        <span className="font-semibold text-slate-700">{d.deal_no}</span>
                        <span className="text-slate-500">{d.deal_name}</span>
                        <span className="text-slate-300">·</span>
                        <span className="text-slate-400">{d.valid_from || "—"} → {d.valid_to || "—"}</span>
                      </span>
                      <span className="text-xs tabular-nums text-slate-600">
                        {d.best_incentive != null ? `₹${inr(d.best_incentive)}` : "—"}
                      </span>
                    </button>

                    {open === d.deal_id && (
                      <div className="px-3 py-2.5 bg-slate-50/60 border-t border-slate-200 space-y-3">
                        <StepRow step={d.deal_validity_step} />
                        {d.plbs.map((p, i) => (
                          <div key={`${d.deal_id}-${p.plb_key}-${i}`} className="pl-2 border-l-2 border-slate-200">
                            <p className="text-[11px] font-semibold text-slate-600 mb-1">{p.plb_key}</p>
                            {p.steps.map((s, j) => <StepRow key={j} step={s} />)}
                            {p.incentive_breakdown?.formula ? (
                              <p className="text-[11px] text-slate-500 mt-1 font-mono">
                                {String(p.incentive_breakdown.formula)}
                              </p>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide text-slate-400">{label}</p>
      <p className="text-slate-700 font-medium">{value || "—"}</p>
    </div>
  );
}

function StepRow({ step }: { step: Step }) {
  return (
    <div className="flex items-start gap-2 text-[11px] py-0.5">
      <StepIcon step={step} />
      <span className="font-medium text-slate-600 w-36 shrink-0">{step.step}</span>
      <span className="text-slate-500">{step.detail}</span>
    </div>
  );
}
