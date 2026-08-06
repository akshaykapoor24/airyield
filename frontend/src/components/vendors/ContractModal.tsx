"use client";

import { useEffect, useMemo, useState } from "react";
import toast from "react-hot-toast";
import { Layers, RefreshCw, Save, X } from "lucide-react";
import api from "@/lib/api";
import { apiError } from "@/components/userMaster/shared";
import AirlinePicker from "@/components/tickets/AirlinePicker";
import SearchSelect from "@/components/ui/SearchSelect";
import PaymentTermsEditor, { type PaymentTerm } from "@/components/vendors/PaymentTermsEditor";

export const CONTRACT_TYPES = ["Series", "SIT", "MICE"] as const;
const TRIP_TYPES = [
  { value: "ONE_WAY", label: "One way" },
  { value: "RETURN", label: "Return" },
] as const;

export type Contract = {
  id: number;
  contract_type: string | null;
  agent_type: string | null;
  agent_name: string | null;
  airline_name: string | null;
  airline_code: string | null;
  pnr_no: string | null;
  pax_count: number | null;
  trip_type: string | null;
  date_of_travel: string | null;
  fare_per_pax: number | null;
  total_fare: number | null;
  payment_terms: PaymentTerm[] | null;
  tickets_issued: number;
  ticket_numbers: string[] | null;
  amount_issued: number;
  match_status: string | null;
  last_matched_at: string | null;
};

type Draft = {
  contract_type: string;
  agent_type: string;
  agent_name: string;
  airline_name: string;
  airline_code: string;
  pnr_no: string;
  pax_count: string;
  trip_type: string;
  date_of_travel: string;
  fare_per_pax: string;
  total_fare: string;
};

const BLANK: Draft = {
  contract_type: "Series", agent_type: "AIRLINE", agent_name: "",
  airline_name: "", airline_code: "", pnr_no: "", pax_count: "",
  trip_type: "RETURN", date_of_travel: "", fare_per_pax: "", total_fare: "",
};

const INPUT =
  "w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30 bg-gray-50";
const LABEL =
  "block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1";

const inr = (v: number | null | undefined) =>
  v == null ? "—" : v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const num = (s: string): number | null => {
  const n = parseFloat(s);
  return Number.isFinite(n) ? n : null;
};

/**
 * Create/edit a Series / SIT / MICE contract.
 *
 * One component for both: passing `contract` means edit. The page owns the list,
 * this owns the form, so the table stays the page's primary content instead of
 * being pushed below a permanently open form.
 */
export default function ContractModal({
  contract, onClose, onSaved,
}: {
  contract?: Contract | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = !!contract?.id;

  const [draft, setDraft] = useState<Draft>(() =>
    contract
      ? {
          contract_type: contract.contract_type ?? "Series",
          agent_type: contract.agent_type ?? "AIRLINE",
          agent_name: contract.agent_name ?? "",
          airline_name: contract.airline_name ?? "",
          airline_code: contract.airline_code ?? "",
          pnr_no: contract.pnr_no ?? "",
          pax_count: contract.pax_count != null ? String(contract.pax_count) : "",
          trip_type: contract.trip_type ?? "RETURN",
          date_of_travel: contract.date_of_travel ?? "",
          fare_per_pax: contract.fare_per_pax != null ? String(contract.fare_per_pax) : "",
          total_fare: contract.total_fare != null ? String(contract.total_fare) : "",
        }
      : BLANK,
  );
  const [terms, setTerms] = useState<PaymentTerm[] | null>(contract?.payment_terms ?? null);
  const [suppliers, setSuppliers] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [touched, setTouched] = useState(false);
  // An existing total is a decision already made, not a leftover to overwrite.
  const [totalTouched, setTotalTouched] = useState(isEdit);

  const isB2B = draft.agent_type === "B2B";

  useEffect(() => {
    if (!isB2B || suppliers.length) return;
    api.get<{ id: number; name: string }[]>("/suppliers/", { params: { limit: 5000 } })
      .then((r) => setSuppliers(r.data.map((s) => s.name)))
      .catch(() => {});
  }, [isB2B, suppliers.length]);

  const set = (key: keyof Draft, value: string) =>
    setDraft((prev) => ({ ...prev, [key]: value }));

  // Total fare tracks pax × fare per pax until the user takes it over — a block
  // deal carries taxes and negotiated totals that break the multiplication.
  const computedTotal = useMemo(() => {
    const pax = num(draft.pax_count);
    const per = num(draft.fare_per_pax);
    return pax != null && per != null ? Math.round(pax * per * 100) / 100 : null;
  }, [draft.pax_count, draft.fare_per_pax]);

  useEffect(() => {
    if (!totalTouched && computedTotal != null) {
      setDraft((prev) => ({ ...prev, total_fare: String(computedTotal) }));
    }
  }, [computedTotal, totalTouched]);

  const totalFare = num(draft.total_fare);
  const totalDiffers =
    totalTouched && computedTotal != null && totalFare != null &&
    Math.abs(computedTotal - totalFare) > 0.01;

  const save = async () => {
    setTouched(true);
    if (!draft.pnr_no.trim()) {
      setError("PNR No is required — it is how tickets are matched to this contract.");
      return;
    }
    setSaving(true); setError("");
    try {
      const payload = {
        contract_type: draft.contract_type || null,
        agent_type: draft.agent_type || null,
        // On an AIRLINE contract the airline IS the counterparty, so there is no
        // separate agent to name. The server mirrors the airline into agent_name.
        agent_name: isB2B ? draft.agent_name.trim() || null : null,
        airline_name: draft.airline_name.trim() || null,
        airline_code: draft.airline_code.trim() || null,
        pnr_no: draft.pnr_no.trim(),
        pax_count: num(draft.pax_count),
        trip_type: draft.trip_type || null,
        date_of_travel: draft.date_of_travel || null,
        fare_per_pax: num(draft.fare_per_pax),
        total_fare: num(draft.total_fare),
        payment_terms: terms,
      };
      if (isEdit) await api.patch(`/series-contracts/${contract!.id}`, payload);
      else await api.post("/series-contracts/", payload);
      toast.success(isEdit ? "Contract updated" : "Contract saved");
      onSaved();
      onClose();
    } catch (e) {
      setError(apiError(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-3xl max-h-[90vh] flex flex-col">
        {/* header */}
        <div
          className="flex items-center justify-between px-6 py-4 rounded-t-2xl shrink-0"
          style={{ background: "#1e3a5f" }}
        >
          <div className="flex items-center gap-2.5">
            <Layers className="w-4 h-4 text-white/80" />
            <h2 className="text-sm font-bold text-white uppercase tracking-wide">
              {isEdit ? "Edit contract" : "Add contract"}
            </h2>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-white/10">
            <X className="w-4 h-4 text-white/80" />
          </button>
        </div>

        {/* body */}
        <div className="px-6 py-4 space-y-4 overflow-y-auto">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-5 gap-y-3">
            <div>
              <label className={LABEL}>Contract Type</label>
              <select value={draft.contract_type} onChange={(e) => set("contract_type", e.target.value)} className={INPUT}>
                {CONTRACT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>

            <div>
              <label className={LABEL}>Agent Type</label>
              <select
                value={draft.agent_type}
                onChange={(e) => { set("agent_type", e.target.value); set("agent_name", ""); }}
                className={INPUT}
              >
                <option value="AIRLINE">Airline</option>
                <option value="B2B">B2B</option>
              </select>
              <p className="text-[10px] text-gray-400 mt-1 leading-snug">
                {isB2B
                  ? "Booked through a consolidator — name the supplier below."
                  : "Booked directly with the airline, so the airline is the counterparty."}
              </p>
            </div>

            {/* Supplier only exists for a B2B contract. On an AIRLINE one the
                airline below already names the party. */}
            {isB2B && (
              <div>
                <label className={LABEL}>Supplier</label>
                <SearchSelect
                  value={draft.agent_name}
                  options={suppliers}
                  onChange={(v) => set("agent_name", v)}
                  placeholder="Select supplier…"
                  allowCustom
                />
              </div>
            )}

            <div>
              <label className={LABEL}>
                PNR No<span className="text-red-500 ml-0.5">*</span>
              </label>
              <input
                value={draft.pnr_no}
                onChange={(e) => set("pnr_no", e.target.value.toUpperCase())}
                placeholder="ABC123"
                className={`${INPUT} font-mono uppercase ${
                  touched && !draft.pnr_no.trim() ? "border-red-300 bg-red-50" : ""
                }`}
              />
              <p className="text-[10px] text-gray-400 mt-1 leading-snug">
                The match key — tickets issued on this PNR roll up into this contract.
              </p>
            </div>

            {/* Airline name + code share one control, backed by the airline master. */}
            <AirlinePicker
              code={draft.airline_code}
              name={draft.airline_name}
              onCodeChange={(v) => set("airline_code", v)}
              onPick={(a) => { set("airline_code", a.iata_code); set("airline_name", a.name); }}
            />

            <div>
              <label className={LABEL}>Pax Count</label>
              <input
                type="number" min="0" step="1"
                value={draft.pax_count}
                onChange={(e) => set("pax_count", e.target.value)}
                placeholder="40"
                className={INPUT}
              />
            </div>

            <div>
              <label className={LABEL}>Trip Type</label>
              <select value={draft.trip_type} onChange={(e) => set("trip_type", e.target.value)} className={INPUT}>
                {TRIP_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
            </div>

            <div>
              <label className={LABEL}>Date of Travel</label>
              <input
                type="date"
                value={draft.date_of_travel}
                onChange={(e) => set("date_of_travel", e.target.value)}
                onClick={(e) => { try { (e.target as HTMLInputElement).showPicker(); } catch {} }}
                className={INPUT}
              />
            </div>

            <div>
              <label className={LABEL}>Fare Per Pax</label>
              <input
                type="number" step="0.01"
                value={draft.fare_per_pax}
                onChange={(e) => set("fare_per_pax", e.target.value)}
                placeholder="25000.00"
                className={INPUT}
              />
            </div>

            <div>
              <label className={LABEL}>Total Fare</label>
              <input
                type="number" step="0.01"
                value={draft.total_fare}
                onChange={(e) => { setTotalTouched(true); set("total_fare", e.target.value); }}
                placeholder="1000000.00"
                className={INPUT}
              />
              <p className="text-[10px] mt-1 leading-snug">
                {totalDiffers ? (
                  <span className="text-amber-600">
                    Pax × fare per pax comes to {inr(computedTotal)} — saved as entered.
                  </span>
                ) : (
                  <span className="text-gray-400">Fills in from pax count × fare per pax; overwrite it if the deal differs.</span>
                )}
              </p>
            </div>
          </div>

          {/* ── Payment term ───────────────────────────────────────────── */}
          <div className="border-t border-gray-100 pt-4">
            <p className="text-[11px] font-bold text-gray-700 uppercase tracking-wide">Payment Term</p>
            <p className="text-[10px] text-gray-400 mt-0.5 mb-2.5 leading-snug">
              One row per instalment — when it falls due, and what share of the total is due by then.
            </p>
            <PaymentTermsEditor value={terms} totalFare={totalFare} onChange={setTerms} />
          </div>

          {error && <p className="text-[11px] text-red-500">{error}</p>}
        </div>

        {/* footer */}
        <div className="px-6 py-4 border-t border-gray-100 flex gap-3 shrink-0">
          <button
            onClick={onClose}
            className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            onClick={save}
            disabled={saving}
            className="flex-1 flex items-center justify-center gap-1.5 bg-[#1e3a5f] hover:bg-[#16304f] text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50"
          >
            {saving
              ? <><RefreshCw className="w-4 h-4 animate-spin" /> Saving…</>
              : <><Save className="w-4 h-4" /> {isEdit ? "Save changes" : "Add contract"}</>}
          </button>
        </div>
      </div>
    </div>
  );
}
