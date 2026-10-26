"use client";

// The deal one statement line was priced with — opened from the Matched deal chip.
//
// Which deal · why it applied (every criterion the matcher tested, with the ticket's value
// against the deal's, and the inclusion / exclusion rules) · what it pays (each incentive on
// its base, IATA % on the BASIC FARE only, their sum against the vendor's statement).
// GET {apiBase}/rows/{calc_id}/applied-deal — services/commission/applied_deal.py. The ⓘ
// popup (CommissionDiagnosisModal) still lists every deal the engine considered.

import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, MinusCircle, X, XCircle } from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { inr } from "./types";

type Criterion = {
  group: string; step: string; passed: boolean; skipped: boolean;
  ticket_value: string; deal_value: string; detail: string;
};
type Rule = {
  kind: string; passed: boolean; reason: string;
  steps: { field: string; rule_value: string; ticket_value: string; matched: boolean }[];
};
type Incentive = {
  incentive_type: string; applied: boolean; calc_on: string;
  basic: number | null; yq: number | null; yr: number | null; base: number | null;
  rate: string | number | null; rate_kind: string; formula: string | null;
  amount: number | null; stored: number | null;
  slab: { period: string | null; range: string | null; achieved: number | null; target: number | null; cell: string | null } | null;
};
type Applied = {
  calc_id: number; status: string; reason: string | null; reversal: boolean;
  ticket: {
    ticket_number: string | null; pnr: string | null; passenger_name: string | null; airline: string | null;
    issue_date: string | null; travel_date: string | null; segment_type: string | null;
    booking_class: string | null; sector: string | null; invoice_type: string | null;
    basic_fare: number | null; yq: number | null; yr: number | null;
  };
  deal: {
    id: number; deal_no: string | null; supplier_name: string | null; airline_name: string | null;
    valid_from: string | null; valid_to: string | null; iata_pct: string | null; match_by: string | null;
  } | null;
  traced: boolean;
  criteria: Criterion[];
  rules: Rule[];
  incentives: Incentive[];
  incentive_total: number;
  iata: { pct: number | null; basic_fare: number; amount: number; formula: string | null };
  expected: number;
  statement: number | null;
  difference: number | null;
  stale: boolean;
};

const pctText = (v: string | number | null) => {
  const n = Number(v);
  return Number.isFinite(n) ? `${n.toLocaleString("en-IN", { maximumFractionDigits: 4 })}%` : `${v ?? "—"}`;
};

export default function AppliedDealModal({
  apiBase, calcId, onClose,
}: { apiBase: string; calcId: number; onClose: () => void }) {
  const [data, setData] = useState<Applied | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api.get<Applied>(`${apiBase}/rows/${calcId}/applied-deal`)
      .then(({ data }) => { if (alive) setData(data); })
      .catch((e: unknown) => {
        const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
        if (alive) setError(msg || "Could not load the deal for this line.");
      });
    return () => { alive = false; };
  }, [apiBase, calcId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const t = data?.ticket;
  const d = data?.deal;
  const groups = data ? [...new Set(data.criteria.map((c) => c.group))] : [];

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 overflow-y-auto" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl w-full max-w-3xl my-8" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between px-5 py-3 border-b border-slate-200">
          <div>
            <h2 className="text-sm font-semibold text-slate-800 flex items-center gap-2">
              Deal applied
              {d?.deal_no && (
                <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold border bg-sky-50 text-sky-700 border-sky-200">
                  {d.deal_no}
                </span>
              )}
            </h2>
            <p className="text-[11px] text-slate-400 mt-0.5">
              Ticket {t?.ticket_number ?? "—"}{t?.passenger_name ? ` · ${t.passenger_name}` : ""}
            </p>
          </div>
          <button onClick={onClose} className="p-1 text-slate-400 hover:text-slate-700" aria-label="Close">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          {error ? (
            <p className="text-sm text-red-500 py-8 text-center">{error}</p>
          ) : !data || !t ? (
            <p className="text-sm text-slate-400 py-8 text-center">Loading…</p>
          ) : (
            <>
              {/* ── The ticket and the deal, side by side ── */}
              <div className="grid md:grid-cols-2 gap-3">
                <Panel title="Ticket — from the statement">
                  <Field label="Airline" value={t.airline} />
                  <Field label="Invoice type" value={t.invoice_type} />
                  <Field label="Issue date" value={t.issue_date} />
                  <Field label="Travel date" value={t.travel_date} />
                  <Field label="Class" value={t.booking_class} />
                  <Field label="Flight type" value={t.segment_type} />
                  <Field label="Sector" value={t.sector} wide />
                  <Field label="Basic fare" value={inr(t.basic_fare)} />
                  <Field label="YQ / YR" value={`${inr(t.yq)} / ${inr(t.yr)}`} />
                </Panel>
                <Panel title="Deal">
                  <Field label="Deal no" value={d?.deal_no} />
                  <Field label="Supplier" value={d?.supplier_name} />
                  <Field label="Airline" value={d?.airline_name} />
                  <Field label="Contract validity" value={d ? `${d.valid_from ?? "—"} → ${d.valid_to ?? "—"}` : null} />
                  <Field label="IATA %" value={d?.iata_pct ? pctText(d.iata_pct) : "not set"} />
                  <Field label="Supplier matched by"
                    value={d?.match_by === "id" ? "Agency / supplier record"
                      : d?.match_by === "name" ? "name only (no branch on the deal)" : d?.match_by ?? null} />
                </Panel>
              </div>

              {data.reversal && (
                <Note tone="sky">
                  This is a refund: it reverses the commission its original sale earned, so the
                  amounts below are that sale&apos;s, given back. {data.reason}
                </Note>
              )}
              {data.stale && (
                <Note tone="amber">
                  The deal has changed since this line was calculated — priced today it gives a
                  different figure from the one stored. Re-run the line (▶) to bring it up to date.
                </Note>
              )}

              {/* ── Why it matched ── */}
              <section>
                <h3 className="text-[11px] uppercase tracking-wide font-semibold text-slate-500 mb-2">Why this deal applied</h3>
                {!data.traced && (
                  <Note tone="slate">
                    The deal could not be traced again right now (the line has no airline or issue
                    date, or the deal is no longer approved). The figures below are the ones calculated.
                  </Note>
                )}
                <div className="border border-slate-200 rounded-lg overflow-hidden">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="bg-slate-50 text-[10px] uppercase tracking-wide text-slate-400">
                        <th className="text-left px-3 py-2 font-semibold">Criterion</th>
                        <th className="text-left px-3 py-2 font-semibold">Ticket</th>
                        <th className="text-left px-3 py-2 font-semibold">Deal</th>
                        <th className="px-3 py-2 w-24" />
                      </tr>
                    </thead>
                    <tbody>
                      {groups.map((g) => (
                        <GroupRows key={g} label={groups.length > 1 ? g : null}
                          rows={data.criteria.filter((c) => c.group === g)} />
                      ))}
                    </tbody>
                  </table>
                </div>
                {data.rules.map((r) => (
                  <div key={r.kind} className="mt-2 border border-slate-200 rounded-lg px-3 py-2">
                    <p className="text-xs flex items-center gap-1.5">
                      {r.passed ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" /> : <XCircle className="w-3.5 h-3.5 text-red-500" />}
                      <span className="font-semibold text-slate-700">{r.kind} rule</span>
                      <span className="text-slate-500">— {r.reason}</span>
                    </p>
                    <ul className="mt-1 ml-5 space-y-0.5">
                      {r.steps.map((s, i) => (
                        <li key={i} className="text-[11px] text-slate-500">
                          {s.field}: rule <span className="font-medium text-slate-600">{s.rule_value}</span>, ticket{" "}
                          <span className="font-medium text-slate-600">{s.ticket_value}</span>{" "}
                          <span className={s.matched ? "text-amber-700" : "text-slate-400"}>{s.matched ? "(matches)" : "(no match)"}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </section>

              {/* ── The arithmetic ── */}
              <section>
                <h3 className="text-[11px] uppercase tracking-wide font-semibold text-slate-500 mb-2">Calculation</h3>
                <div className="border border-slate-200 rounded-lg divide-y divide-slate-100">
                  {data.incentives.map((inc) => (
                    <div key={inc.incentive_type} className={cn("px-3 py-2.5", !inc.applied && "opacity-60")}>
                      <p className="text-xs font-semibold text-slate-700 mb-1">
                        {inc.incentive_type}
                        <span className="font-normal text-slate-400"> · calculated on {inc.calc_on}</span>
                        {!inc.applied && <span className="ml-1.5 text-[10px] font-semibold text-red-500">did not apply</span>}
                      </p>
                      {inc.slab ? (
                        <Line label={`Slab ${inc.slab.cell ?? ""} · ${inc.slab.period ?? ""}`}
                          value={inc.formula ?? "—"} mono />
                      ) : (
                        <>
                          <Line label="Basic fare" value={inr(inc.basic)} />
                          {inc.yq != null && <Line label="+ YQ" value={inr(inc.yq)} />}
                          {inc.yr != null && <Line label="+ YR" value={inr(inc.yr)} />}
                          <Line label="= Base" value={inr(inc.base)} strong />
                          <Line label={inc.rate_kind?.toLowerCase().startsWith("percent") ? "× Rate" : "Flat amount"}
                            value={inc.rate_kind?.toLowerCase().startsWith("percent") ? pctText(inc.rate) : `₹${inr(Number(inc.rate))}`} />
                        </>
                      )}
                      <Line label={`= ${inc.incentive_type}`} value={`₹${inr(inc.amount)}`} strong tone="text-emerald-700" />
                    </div>
                  ))}

                  <div className="px-3 py-2.5">
                    <p className="text-xs font-semibold text-slate-700 mb-1">
                      IATA commission <span className="font-normal text-slate-400">· on the basic fare only — YQ, YR and taxes never count</span>
                    </p>
                    {data.iata.pct ? (
                      <>
                        <Line label="Basic fare" value={inr(data.iata.basic_fare)} />
                        <Line label="× IATA %" value={pctText(data.iata.pct)} />
                        <Line label="= IATA commission" value={`₹${inr(data.iata.amount)}`} strong tone="text-teal-700" />
                      </>
                    ) : (
                      <p className="text-[11px] text-slate-500">
                        This deal has no IATA % set, so no IATA commission — ₹0.00.
                      </p>
                    )}
                  </div>

                  <div className="px-3 py-2.5 bg-slate-50/70">
                    <Line label="Incentive" value={`₹${inr(data.incentive_total)}`} />
                    <Line label="+ IATA commission" value={`₹${inr(data.iata.amount)}`} />
                    <Line label="= Expected commission" value={`₹${inr(data.expected)}`} strong tone="text-emerald-700" />
                    <Line label="Commission in statement (vendor)"
                      value={data.statement != null ? `₹${inr(data.statement)}` : "—"} />
                    <Line label="Difference (expected − statement)"
                      value={data.difference != null ? `${data.difference > 0 ? "+" : data.difference < 0 ? "−" : ""}₹${inr(Math.abs(data.difference))}` : "—"}
                      strong
                      tone={data.difference == null || Math.abs(data.difference) < 1 ? "text-emerald-700"
                        : data.difference > 0 ? "text-amber-700" : "text-slate-600"} />
                    {data.difference != null && Math.abs(data.difference) >= 1 && (
                      <p className="text-[11px] text-slate-500 text-right mt-0.5">
                        {data.difference > 0 ? "The vendor paid you less than this deal says — they owe you."
                          : "The vendor paid you more than this deal says."}
                      </p>
                    )}
                  </div>
                </div>
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-slate-50 border border-slate-200 rounded-lg p-3">
      <p className="text-[10px] uppercase tracking-wide text-slate-400 font-semibold mb-2">{title}</p>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">{children}</div>
    </div>
  );
}

function Field({ label, value, wide }: { label: string; value: string | null | undefined; wide?: boolean }) {
  return (
    <div className={wide ? "col-span-2" : undefined}>
      <p className="text-[10px] uppercase tracking-wide text-slate-400">{label}</p>
      <p className="text-slate-700 font-medium break-words">{value || "—"}</p>
    </div>
  );
}

function GroupRows({ label, rows }: { label: string | null; rows: Criterion[] }) {
  return (
    <>
      {label && (
        <tr className="bg-slate-50/60"><td colSpan={4} className="px-3 py-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</td></tr>
      )}
      {rows.map((c, i) => (
        <tr key={`${c.step}-${i}`} className="border-t border-slate-100 align-top" title={c.detail}>
          <td className="px-3 py-1.5 font-medium text-slate-600 whitespace-nowrap">{c.step}</td>
          <td className="px-3 py-1.5 text-slate-600">{c.ticket_value}</td>
          <td className="px-3 py-1.5 text-slate-600">{c.deal_value}</td>
          <td className="px-3 py-1.5 whitespace-nowrap">
            {c.skipped ? (
              <span className="inline-flex items-center gap-1 text-slate-400"><MinusCircle className="w-3.5 h-3.5" /> not printed</span>
            ) : c.passed ? (
              <span className="inline-flex items-center gap-1 text-emerald-600"><CheckCircle2 className="w-3.5 h-3.5" /> match</span>
            ) : (
              <span className="inline-flex items-center gap-1 text-red-500"><XCircle className="w-3.5 h-3.5" /> no match</span>
            )}
          </td>
        </tr>
      ))}
    </>
  );
}

function Line({ label, value, strong, tone, mono }: {
  label: string; value: string; strong?: boolean; tone?: string; mono?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 text-xs py-0.5">
      <span className="text-slate-500">{label}</span>
      <span className={cn("tabular-nums", strong && "font-semibold", tone ?? "text-slate-700", mono && "font-mono")}>{value}</span>
    </div>
  );
}

function Note({ tone, children }: { tone: "amber" | "sky" | "slate"; children: React.ReactNode }) {
  const cls = { amber: "border-amber-200 bg-amber-50 text-amber-800", sky: "border-sky-200 bg-sky-50 text-sky-800",
                slate: "border-slate-200 bg-slate-50 text-slate-600" }[tone];
  return (
    <div className={cn("flex items-start gap-2 px-3 py-2 rounded-lg border text-xs mb-2", cls)}>
      <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-px" />
      <span>{children}</span>
    </div>
  );
}
