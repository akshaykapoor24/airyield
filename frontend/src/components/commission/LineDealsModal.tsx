"use client";

// Every deal for one ticket line — opened from its Result badge in the commission check.
//
// The deal that applied comes first, worked through (AppliedDealBody: why it applied, how it
// pays, against the vendor's statement). Below it, every other deal the engine considered
// for the ticket, in two groups: those that also cover it but were not used (the applied one
// pays at least as much after its rules), and those that do not apply — each with the check
// it failed written on its row, and every check one click away (DealDiagDetail).
//
// Two reads: GET …/rows/{id}/applied-deal (only when a deal applied) and
// GET …/rows/{id}/match-diagnosis (always) — the same two the separate popups used.

import { useEffect, useState } from "react";
import { CheckCircle2, ChevronDown, ChevronRight, X, XCircle } from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { AppliedDealBody, useAppliedDeal } from "./AppliedDealModal";
import {
  DealDiagDetail, excludingRule, whyNot, type DealDiag, type Diagnosis,
} from "./CommissionDiagnosisModal";
import { CommissionRow, STATUS_STYLE, inr } from "./types";

/** Covers the ticket on every criterion and none of its rules leaves it out. */
const applies = (d: DealDiag) => d.overall_match && !excludingRule(d);

export default function LineDealsModal({
  apiBase, calc, dealKind, onClose,
}: {
  apiBase: string;
  calc: CommissionRow;
  /** "B2B" / "AIR" — the prefix on the applied deal's name. */
  dealKind: string;
  onClose: () => void;
}) {
  const appliedId = calc.matched_deal_id;
  const applied = useAppliedDeal(apiBase, appliedId ? calc.id : null);
  const [diag, setDiag] = useState<Diagnosis | null>(null);
  const [diagError, setDiagError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api.get<Diagnosis>(`${apiBase}/rows/${calc.id}/match-diagnosis`)
      .then(({ data }) => { if (alive) setDiag(data); })
      .catch(() => { if (alive) setDiagError("Could not load the other deals for this ticket."); });
    return () => { alive = false; };
  }, [apiBase, calc.id]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const st = STATUS_STYLE[calc.commission_status] ?? STATUS_STYLE.pending;
  const others = (diag?.deals ?? []).filter((d) => d.deal_id !== appliedId);
  const alsoApply = others.filter(applies);
  const dontApply = others.filter((d) => !applies(d));
  const notes = calc.notes ?? [];
  const appliedTitle = calc.commission_status === "excluded"
    ? "Deal matched — but its rules leave this ticket out"
    : calc.commission_status === "reversed" ? "Deal reversed — the refund gives back the sale's commission"
    : "Deal applied";

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 overflow-y-auto" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl w-full max-w-4xl my-8" onClick={(e) => e.stopPropagation()}>
        {/* ── Header ── */}
        <div className="flex items-start justify-between gap-3 px-5 py-3 border-b border-slate-200">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-slate-800 flex items-center gap-2 flex-wrap">
              Deals for ticket {calc.ticket_number ?? "—"}
              <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border ${st.cls}`}>
                {st.label}
              </span>
            </h2>
            <p className="text-[11px] text-slate-400 mt-0.5 truncate">
              {[calc.passenger_name, calc.airline_name, calc.issue_date].filter(Boolean).join(" · ")}
              {diag && ` · ${diag.total_deals_checked} deal${diag.total_deals_checked === 1 ? "" : "s"} checked`}
            </p>
          </div>
          <button onClick={onClose} className="p-1 text-slate-400 hover:text-slate-700 shrink-0" aria-label="Close">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-5">
          {(calc.commission_reason || notes.length > 0) && (
            <div className="space-y-1.5">
              {calc.commission_reason && (
                <p className="text-xs text-slate-600 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2">
                  <span className="font-semibold">Result:</span> {calc.commission_reason}
                </p>
              )}
              {notes.map((n, i) => (
                <p key={i} className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-1.5">⚠ {n}</p>
              ))}
            </div>
          )}

          {/* ── The deal that applied ── */}
          <section>
            <SectionTitle>{appliedId ? appliedTitle : "No deal applied"}</SectionTitle>
            {appliedId ? (
              <div className="border border-emerald-200 rounded-lg overflow-hidden">
                <div className="flex items-center justify-between gap-3 px-3 py-2 bg-emerald-50/70 border-b border-emerald-200">
                  <span className="flex items-center gap-2 text-xs min-w-0">
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 shrink-0" />
                    <span className="font-semibold text-slate-800">{calc.matched_deal_no ?? "Deal"}</span>
                    <span className="text-slate-600 truncate">{dealKind} · {calc.matched_deal_name}</span>
                    {calc.supplier_match_by === "name" && (
                      <span className="text-[10px] font-semibold text-amber-700 bg-amber-50 border border-amber-200 rounded px-1 shrink-0"
                        title="Matched by supplier NAME only — the deal is not linked to an Agency Master branch.">
                        name only
                      </span>
                    )}
                  </span>
                  {applied.data && (
                    <span className="text-xs tabular-nums font-semibold text-emerald-700 shrink-0">
                      ₹{inr(applied.data.expected)} expected
                    </span>
                  )}
                </div>
                <div className="p-3">
                  {applied.error ? (
                    <p className="text-sm text-red-500 py-6 text-center">{applied.error}</p>
                  ) : !applied.data ? (
                    <p className="text-sm text-slate-400 py-6 text-center">Loading…</p>
                  ) : (
                    <AppliedDealBody data={applied.data} />
                  )}
                </div>
              </div>
            ) : (
              <p className="text-xs text-orange-700 bg-orange-50 border border-orange-200 rounded-lg px-3 py-2">
                {diag?.note
                  ?? (calc.commission_status === "skipped"
                    ? "This line is not a sale, so no deal is looked for."
                    : "None of the deals below covers this ticket — each shows the check it failed.")}
              </p>
            )}
          </section>

          {/* ── Every other deal considered ── */}
          <section>
            <SectionTitle>
              {appliedId ? "Other deals checked" : "Deals checked"}
              {diag && <span className="font-normal normal-case tracking-normal text-slate-400"> · {others.length}</span>}
            </SectionTitle>
            {diagError ? (
              <p className="text-sm text-red-500 py-4 text-center">{diagError}</p>
            ) : !diag ? (
              <p className="text-sm text-slate-400 py-4 text-center">Loading…</p>
            ) : others.length === 0 ? (
              <p className="text-xs text-slate-500">
                {appliedId ? "No other deal covers this airline for this consolidator." : "No deal covers this airline for this consolidator."}
              </p>
            ) : (
              <div className="space-y-3">
                {alsoApply.length > 0 && (
                  <DealGroup title={`Also cover this ticket — not used (${alsoApply.length})`}
                    hint="They pass every check, but the applied deal pays at least as much after its rules.">
                    {alsoApply.map((d) => <DealRow key={d.deal_id} deal={d} />)}
                  </DealGroup>
                )}
                {dontApply.length > 0 && (
                  <DealGroup title={`Do not apply (${dontApply.length})`}
                    hint="Each fails at least one check — the first is shown; open a deal for all of them.">
                    {dontApply.map((d) => <DealRow key={d.deal_id} deal={d} />)}
                  </DealGroup>
                )}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 className="text-[11px] uppercase tracking-wide font-semibold text-slate-500 mb-2">{children}</h3>;
}

function DealGroup({ title, hint, children }: { title: string; hint: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs font-semibold text-slate-700">{title}</p>
      <p className="text-[11px] text-slate-400 mb-1.5">{hint}</p>
      <div className="space-y-1.5">{children}</div>
    </div>
  );
}

/** One other deal: whether it covers the ticket, the first check it failed, and — opened —
 *  every check it went through. */
function DealRow({ deal: d }: { deal: DealDiag }) {
  const [open, setOpen] = useState(false);
  const ok = applies(d);
  const why = whyNot(d);
  return (
    <div className={cn("border rounded-lg overflow-hidden", ok ? "border-emerald-200" : "border-slate-200")}>
      <button onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between gap-3 px-3 py-2 hover:bg-slate-50 text-left">
        <span className="min-w-0">
          <span className="flex items-center gap-2 text-xs">
            {open ? <ChevronDown className="w-3.5 h-3.5 text-slate-400 shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 text-slate-400 shrink-0" />}
            {ok
              ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 shrink-0" />
              : <XCircle className="w-3.5 h-3.5 text-red-400 shrink-0" />}
            <span className="font-semibold text-slate-700">{d.deal_no}</span>
            <span className="text-slate-500 truncate">{d.deal_name}</span>
            <span className="text-slate-300">·</span>
            <span className="text-slate-400 whitespace-nowrap">{d.valid_from || "—"} → {d.valid_to || "—"}</span>
          </span>
          {why && (
            <span className="block text-[11px] text-red-600 mt-0.5 ml-[3.25rem] truncate" title={why.full || why.label}>
              {why.label}
            </span>
          )}
        </span>
        <span className="text-xs tabular-nums text-slate-600 shrink-0">
          {d.best_incentive != null ? `₹${inr(d.best_incentive)}` : "—"}
        </span>
      </button>
      {open && <DealDiagDetail deal={d} />}
    </div>
  );
}
