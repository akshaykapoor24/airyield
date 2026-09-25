"use client";

/**
 * The money side of a contract: what the fare is made of, what is owed when, and what
 * has actually been paid.
 *
 * The fare is editable as components rather than as one number because a penalty has to
 * name the base it applies to — and the two bases in common use ("net fare" and "airline
 * retention", which is base + YQ) are different sums over those components.
 */

import { useState } from "react";
import toast from "react-hot-toast";
import { Banknote, Check, Loader2, Save } from "lucide-react";

import api from "@/lib/api";
import { apiError } from "@/components/userMaster/shared";
import {
  API_BASE, COMPONENT_LABEL, FARE_BASIS_LABEL, PAYMENT_KIND_LABEL,
  type ContractDetail, inr, relativeDays,
} from "@/lib/series";
import {
  FareEditor, SMALL_INPUT, num, type FareDraft,
} from "./editors";

export default function MoneyTab({
  contract, onChanged,
}: {
  contract: ContractDetail;
  onChanged: (next: ContractDetail) => void;
}) {
  const [editingFare, setEditingFare] = useState(false);
  const [fare, setFare] = useState<FareDraft[]>([]);
  const [saving, setSaving] = useState(false);
  const [payFor, setPayFor] = useState<number | null>(null);

  const startEditingFare = () => {
    setFare(
      contract.fare_components
        .filter((c) => c.allocation_id == null)
        .map((c) => ({
          component_code: c.component_code ?? "BASE",
          label: c.label ?? "",
          amount_per_pax: c.amount_per_pax != null ? String(c.amount_per_pax) : "",
          is_guaranteed_until_ticketing: !!c.is_guaranteed_until_ticketing,
          is_refundable_on_noshow: !!c.is_refundable_on_noshow,
        })),
    );
    setEditingFare(true);
  };

  const saveFare = async () => {
    setSaving(true);
    try {
      const { data } = await api.put<ContractDetail>(
        `${API_BASE}/${contract.id}/fare-components`,
        fare
          .filter((f) => num(f.amount_per_pax) != null)
          .map((f, i) => ({
            component_code: f.component_code,
            label: f.label.trim() || null,
            amount_per_pax: num(f.amount_per_pax),
            is_guaranteed_until_ticketing: f.is_guaranteed_until_ticketing,
            is_refundable_on_noshow: f.is_refundable_on_noshow,
            sort_order: i,
          })),
      );
      onChanged(data);
      setEditingFare(false);
      toast.success("Fare updated");
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSaving(false);
    }
  };

  const summary = contract.fare_summary;

  return (
    <div className="space-y-4">
      {/* Fare */}
      <section className="bg-white rounded-xl border border-gray-100 shadow-sm">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100">
          <p className="text-xs font-bold text-gray-800 uppercase tracking-wide">Contracted fare</p>
          <div className="ml-auto flex gap-2">
            {editingFare ? (
              <>
                <button
                  onClick={() => setEditingFare(false)}
                  className="px-3 py-1.5 text-[11px] font-semibold text-gray-500 hover:bg-gray-50 rounded-lg"
                >
                  Cancel
                </button>
                <button
                  onClick={saveFare}
                  disabled={saving}
                  className="flex items-center gap-1.5 bg-[#1e3a5f] hover:bg-[#16304f] text-white text-[11px] font-semibold px-3 py-1.5 rounded-lg disabled:opacity-60"
                >
                  {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />}
                  Save fare
                </button>
              </>
            ) : (
              <button
                onClick={startEditingFare}
                className="px-3 py-1.5 text-[11px] font-semibold text-[#1e3a5f] hover:bg-gray-50 rounded-lg"
              >
                Edit fare
              </button>
            )}
          </div>
        </div>

        <div className="px-4 py-3">
          {editingFare ? (
            <FareEditor value={fare} onChange={setFare} seats={summary.seats} />
          ) : contract.fare_components.length === 0 ? (
            <p className="text-xs text-gray-400 py-4 text-center">
              No fare entered yet. Without it the contract has no cost and no margin.
            </p>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div>
                <table className="w-full">
                  <tbody>
                    {contract.fare_components
                      .filter((c) => c.allocation_id == null)
                      .map((c) => (
                        <tr key={c.id} className="border-b border-gray-50">
                          <td className="py-1.5 text-[11px] text-gray-600">
                            {c.label || COMPONENT_LABEL[c.component_code ?? ""] || c.component_code}
                            <span className="ml-1.5 inline-flex gap-1">
                              {c.is_guaranteed_until_ticketing && (
                                <span
                                  className="text-[9px] px-1 rounded bg-emerald-50 text-emerald-600"
                                  title="Guaranteed until ticketing"
                                >
                                  frozen
                                </span>
                              )}
                              {c.is_refundable_on_noshow && (
                                <span
                                  className="text-[9px] px-1 rounded bg-blue-50 text-blue-600"
                                  title="Refundable when a passenger no-shows"
                                >
                                  refundable
                                </span>
                              )}
                            </span>
                          </td>
                          <td className="py-1.5 text-[11px] text-gray-800 tabular-nums text-right">
                            {inr(c.amount_per_pax)}
                          </td>
                        </tr>
                      ))}
                    <tr>
                      <td className="py-2 text-[11px] font-bold text-gray-800">Per passenger</td>
                      <td className="py-2 text-[11px] font-bold text-gray-900 tabular-nums text-right">
                        {inr(summary.per_pax)}
                      </td>
                    </tr>
                    <tr>
                      <td className="py-1 text-[11px] text-gray-500">× {summary.seats} seats</td>
                      <td className="py-1 text-[11px] font-bold text-gray-900 tabular-nums text-right">
                        {inr(summary.total)}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <div>
                <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-1.5">
                  Penalty bases — per passenger
                </p>
                <table className="w-full">
                  <tbody>
                    {Object.entries(summary.bases).map(([basis, value]) => (
                      <tr key={basis} className="border-b border-gray-50">
                        <td className="py-1.5 text-[11px] text-gray-600">{FARE_BASIS_LABEL[basis] ?? basis}</td>
                        <td className="py-1.5 text-[11px] text-gray-800 tabular-nums text-right">{inr(value)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="text-[10px] text-gray-400 mt-2">
                  A percentage penalty means nothing without one of these. Of the per-passenger
                  fare, <span className="font-medium text-gray-600">{inr(summary.guaranteed_per_pax)}</span>{" "}
                  is frozen until ticketing and{" "}
                  <span className="font-medium text-gray-600">{inr(summary.exposed_per_pax)}</span>{" "}
                  can still move.
                </p>
              </div>
            </div>
          )}
        </div>
      </section>

      {/* Schedule */}
      <section className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100">
          <p className="text-xs font-bold text-gray-800 uppercase tracking-wide">Payment schedule</p>
          <span className="ml-auto text-[11px] text-gray-500">
            Outstanding{" "}
            <span className={`font-semibold tabular-nums ${contract.overdue_count ? "text-red-600" : "text-gray-800"}`}>
              {inr(contract.amount_due)}
            </span>
          </span>
        </div>

        {contract.payment_schedule.length === 0 ? (
          <p className="text-xs text-gray-400 py-8 text-center">No instalments recorded.</p>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50">
                {["INSTALMENT", "DUE", "AMOUNT", "PAID", "OUTSTANDING", "STATUS", ""].map((h) => (
                  <th key={h} className="px-3 py-2 text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wider">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {contract.payment_schedule.map((row) => (
                <tr key={row.id} className="border-b border-gray-50">
                  <td className="px-3 py-2 text-[11px] text-gray-700">
                    {PAYMENT_KIND_LABEL[row.kind ?? ""] ?? row.kind ?? "—"}
                    {row.pct != null && row.pct_basis && (
                      <span className="block text-[9px] text-gray-400">
                        {row.pct}% of {FARE_BASIS_LABEL[row.pct_basis] ?? row.pct_basis}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-[11px] text-gray-600 whitespace-nowrap">
                    {row.due_date ?? "—"}
                    {row.due_date && row.status !== "paid" && row.status !== "waived" && (
                      <span className={`block text-[9px] ${row.is_overdue ? "text-red-500 font-semibold" : "text-gray-400"}`}>
                        {relativeDays(row.days_remaining)}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-[11px] text-gray-800 tabular-nums">{inr(row.amount)}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600 tabular-nums">{inr(row.paid_amount)}</td>
                  <td className="px-3 py-2 text-[11px] tabular-nums">
                    <span className={row.is_overdue ? "text-red-600 font-semibold" : "text-gray-600"}>
                      {inr(row.outstanding)}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <StatusPill status={row.status} overdue={row.is_overdue} />
                  </td>
                  <td className="px-3 py-2 text-right">
                    {row.status !== "paid" && row.status !== "waived" && (
                      <button
                        onClick={() => setPayFor(payFor === row.id ? null : row.id)}
                        className="inline-flex items-center gap-1 text-[11px] font-semibold text-[#1e3a5f] hover:bg-gray-50 px-2 py-1 rounded-lg"
                      >
                        <Banknote className="w-3 h-3" /> Record payment
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {payFor != null && (
          <PaymentForm
            contractId={contract.id}
            scheduleId={payFor}
            suggested={contract.payment_schedule.find((s) => s.id === payFor)?.outstanding ?? 0}
            onDone={(next) => { setPayFor(null); onChanged(next); }}
            onCancel={() => setPayFor(null)}
          />
        )}

        <p className="px-4 py-2 text-[10px] text-gray-400 border-t border-gray-100">
          Overdue is worked out against today&apos;s date each time this loads, never stored —
          so it is right on the day it becomes true rather than the next time a job runs.
        </p>
      </section>
    </div>
  );
}

function StatusPill({ status, overdue }: { status?: string | null; overdue?: boolean }) {
  if (overdue && status !== "paid" && status !== "waived") {
    return (
      <span className="inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold border bg-red-50 text-red-700 border-red-200">
        Overdue
      </span>
    );
  }
  const map: Record<string, string> = {
    pending: "bg-gray-50 text-gray-500 border-gray-200",
    partial: "bg-amber-50 text-amber-700 border-amber-200",
    paid: "bg-emerald-50 text-emerald-700 border-emerald-200",
    waived: "bg-slate-100 text-slate-600 border-slate-200",
  };
  const label: Record<string, string> = {
    pending: "Pending", partial: "Part paid", paid: "Paid", waived: "Waived",
  };
  const key = status ?? "pending";
  return (
    <span className={`inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold border ${map[key] ?? map.pending}`}>
      {label[key] ?? key}
    </span>
  );
}

function PaymentForm({
  contractId, scheduleId, suggested, onDone, onCancel,
}: {
  contractId: number;
  scheduleId: number;
  suggested: number;
  onDone: (c: ContractDetail) => void;
  onCancel: () => void;
}) {
  const [amount, setAmount] = useState(suggested > 0 ? String(suggested) : "");
  const [paidOn, setPaidOn] = useState("");
  const [method, setMethod] = useState("");
  const [reference, setReference] = useState("");
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    const value = num(amount);
    if (value == null || value <= 0) {
      toast.error("Enter the amount that was paid.");
      return;
    }
    setSaving(true);
    try {
      const { data } = await api.post<ContractDetail>(
        `${API_BASE}/${contractId}/payment-schedule/${scheduleId}/payments`,
        {
          amount: value,
          paid_on: paidOn || null,
          method: method.trim() || null,
          reference: reference.trim() || null,
        },
      );
      toast.success("Payment recorded");
      onDone(data);
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="px-4 py-3 bg-blue-50/40 border-t border-blue-100">
      <div className="grid grid-cols-[130px_130px_1fr_1fr_auto_auto] gap-2 items-end">
        <div>
          <label className="block text-[10px] font-semibold text-gray-500 uppercase mb-1">Amount</label>
          <input
            type="number"
            step="0.01"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className={`${SMALL_INPUT} tabular-nums text-right`}
          />
        </div>
        <div>
          <label className="block text-[10px] font-semibold text-gray-500 uppercase mb-1">Paid on</label>
          <input type="date" value={paidOn} onChange={(e) => setPaidOn(e.target.value)} className={SMALL_INPUT} />
        </div>
        <div>
          <label className="block text-[10px] font-semibold text-gray-500 uppercase mb-1">Method</label>
          <input
            value={method}
            onChange={(e) => setMethod(e.target.value)}
            placeholder="Bank transfer"
            className={SMALL_INPUT}
          />
        </div>
        <div>
          <label className="block text-[10px] font-semibold text-gray-500 uppercase mb-1">Reference</label>
          <input
            value={reference}
            onChange={(e) => setReference(e.target.value)}
            placeholder="UTR / voucher"
            className={SMALL_INPUT}
          />
        </div>
        <button onClick={onCancel} className="px-3 py-1.5 text-[11px] font-semibold text-gray-500 hover:bg-white rounded-lg">
          Cancel
        </button>
        <button
          onClick={submit}
          disabled={saving}
          className="flex items-center gap-1.5 bg-[#1e3a5f] hover:bg-[#16304f] text-white text-[11px] font-semibold px-3 py-1.5 rounded-lg disabled:opacity-60"
        >
          {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
          Record
        </button>
      </div>
      <p className="text-[10px] text-gray-400 mt-1.5">
        Paying the advance deposit in full firms the group size on every departure that has
        not been firmed yet — that is the number the materialisation floor is measured against.
      </p>
    </div>
  );
}
