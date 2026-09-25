"use client";

/**
 * The three repeatable editors a series contract needs — departures (with their flight
 * legs), the fare broken into components, and the payment schedule.
 *
 * They live together and are exported separately because both the create wizard and the
 * contract detail screen use all three, and keeping one copy is what stops the two
 * screens drifting into disagreeing about what a valid fare looks like.
 *
 * Each is controlled: it holds strings internally (so a half-typed number does not become
 * NaN mid-keystroke) and hands the parent a typed array on every change. Same shape as
 * `PaymentTermsEditor`, which this replaces.
 */

import { Plus, Trash2 } from "lucide-react";
import {
  CABINS, CABIN_LABEL, COMPONENT_CODES, COMPONENT_LABEL, FARE_BASES,
  FARE_BASIS_LABEL, PAYMENT_KINDS, PAYMENT_KIND_LABEL, inr,
} from "@/lib/series";

export const INPUT =
  "w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30 bg-gray-50";
export const SMALL_INPUT =
  "w-full border border-gray-200 rounded-md px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-[#1e3a5f]/40 bg-white";
export const LABEL =
  "block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1";

const MAX_ROWS = 60;

export const num = (v: string): number | null => {
  const t = v.trim();
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
};

const AddRow = ({ onClick, label, disabled }: { onClick: () => void; label: string; disabled?: boolean }) => (
  <button
    type="button"
    onClick={onClick}
    disabled={disabled}
    className="flex items-center gap-1.5 text-[11px] font-semibold text-[#1e3a5f] hover:text-[#16304f] disabled:opacity-40 mt-2"
  >
    <Plus className="w-3.5 h-3.5" /> {label}
  </button>
);

const DeleteCell = ({ onClick, title }: { onClick: () => void; title: string }) => (
  <button type="button" onClick={onClick} title={title} className="p-1.5 hover:bg-red-50 rounded-lg">
    <Trash2 className="w-3.5 h-3.5 text-red-400" />
  </button>
);

// ── Departures ───────────────────────────────────────────────────────────────

export type SectorDraft = {
  direction: string;
  origin: string;
  destination: string;
  airline_code: string;
  flight_number: string;
  departure_at: string;
  arrival_at: string;
  cabin: string;
  rbd: string;
};

export type AllocationDraft = {
  allocation_ref: string;
  departure_date: string;
  requested_pax: string;
  firmed_pax: string;
  sectors: SectorDraft[];
};

export const blankSector = (): SectorDraft => ({
  direction: "OUTBOUND", origin: "", destination: "", airline_code: "",
  flight_number: "", departure_at: "", arrival_at: "", cabin: "", rbd: "",
});

export const blankAllocation = (): AllocationDraft => ({
  allocation_ref: "", departure_date: "", requested_pax: "", firmed_pax: "",
  sectors: [blankSector()],
});

export function AllocationsEditor({
  value, onChange, defaultCabin,
}: {
  value: AllocationDraft[];
  onChange: (v: AllocationDraft[]) => void;
  defaultCabin?: string;
}) {
  const setAt = (i: number, patch: Partial<AllocationDraft>) =>
    onChange(value.map((a, idx) => (idx === i ? { ...a, ...patch } : a)));

  const setSector = (ai: number, si: number, patch: Partial<SectorDraft>) =>
    onChange(value.map((a, idx) =>
      idx !== ai ? a : { ...a, sectors: a.sectors.map((s, sx) => (sx === si ? { ...s, ...patch } : s)) },
    ));

  return (
    <div className="space-y-3">
      {value.map((alloc, ai) => (
        <div key={ai} className="border border-gray-200 rounded-lg p-3 bg-gray-50/40">
          <div className="flex items-center gap-2 mb-2">
            <p className="text-[11px] font-bold text-gray-700 uppercase tracking-wide">
              Departure {ai + 1}
            </p>
            {value.length > 1 && (
              <div className="ml-auto">
                <DeleteCell onClick={() => onChange(value.filter((_, x) => x !== ai))} title="Remove departure" />
              </div>
            )}
          </div>

          <div className="grid grid-cols-4 gap-2 mb-3">
            <div>
              <label className={LABEL}>Reference</label>
              <input
                value={alloc.allocation_ref}
                onChange={(e) => setAt(ai, { allocation_ref: e.target.value })}
                placeholder={`A${ai + 1}`}
                className={SMALL_INPUT}
              />
            </div>
            <div>
              <label className={LABEL}>Departure date</label>
              <input
                type="date"
                value={alloc.departure_date}
                onChange={(e) => setAt(ai, { departure_date: e.target.value })}
                className={SMALL_INPUT}
              />
            </div>
            <div>
              <label className={LABEL}>Seats</label>
              <input
                type="number"
                min="1"
                value={alloc.requested_pax}
                onChange={(e) => setAt(ai, { requested_pax: e.target.value })}
                placeholder="60"
                className={SMALL_INPUT}
              />
            </div>
            <div>
              <label className={LABEL} title="Set when the advance deposit is paid">
                Firmed
              </label>
              <input
                type="number"
                min="0"
                value={alloc.firmed_pax}
                onChange={(e) => setAt(ai, { firmed_pax: e.target.value })}
                placeholder="—"
                className={SMALL_INPUT}
              />
            </div>
          </div>

          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-1">
            Flight legs
          </p>
          <div className="space-y-1.5">
            {alloc.sectors.map((s, si) => (
              <div key={si} className="grid grid-cols-[90px_70px_70px_70px_90px_1fr_1fr_28px] gap-1.5 items-end">
                <div>
                  {si === 0 && <label className={LABEL}>Direction</label>}
                  <select
                    value={s.direction}
                    onChange={(e) => setSector(ai, si, { direction: e.target.value })}
                    className={SMALL_INPUT}
                  >
                    <option value="OUTBOUND">Outbound</option>
                    <option value="INBOUND">Inbound</option>
                  </select>
                </div>
                <div>
                  {si === 0 && <label className={LABEL}>From</label>}
                  <input
                    value={s.origin}
                    onChange={(e) => setSector(ai, si, { origin: e.target.value.toUpperCase() })}
                    placeholder="DEL"
                    maxLength={3}
                    className={`${SMALL_INPUT} font-mono uppercase`}
                  />
                </div>
                <div>
                  {si === 0 && <label className={LABEL}>To</label>}
                  <input
                    value={s.destination}
                    onChange={(e) => setSector(ai, si, { destination: e.target.value.toUpperCase() })}
                    placeholder="ATQ"
                    maxLength={3}
                    className={`${SMALL_INPUT} font-mono uppercase`}
                  />
                </div>
                <div>
                  {si === 0 && <label className={LABEL}>Flight</label>}
                  <input
                    value={s.flight_number}
                    onChange={(e) => setSector(ai, si, { flight_number: e.target.value.toUpperCase() })}
                    placeholder="AI-495"
                    className={`${SMALL_INPUT} font-mono uppercase`}
                  />
                </div>
                <div>
                  {si === 0 && <label className={LABEL}>RBD</label>}
                  <input
                    value={s.rbd}
                    onChange={(e) => setSector(ai, si, { rbd: e.target.value.toUpperCase() })}
                    placeholder="U"
                    maxLength={4}
                    className={`${SMALL_INPUT} font-mono uppercase`}
                  />
                </div>
                <div>
                  {si === 0 && <label className={LABEL}>Departs</label>}
                  <input
                    type="datetime-local"
                    value={s.departure_at}
                    onChange={(e) => setSector(ai, si, { departure_at: e.target.value })}
                    className={SMALL_INPUT}
                  />
                </div>
                <div>
                  {si === 0 && <label className={LABEL}>Arrives</label>}
                  <input
                    type="datetime-local"
                    value={s.arrival_at}
                    onChange={(e) => setSector(ai, si, { arrival_at: e.target.value })}
                    className={SMALL_INPUT}
                  />
                </div>
                <div className="pb-0.5">
                  {alloc.sectors.length > 1 && (
                    <DeleteCell
                      onClick={() => setAt(ai, { sectors: alloc.sectors.filter((_, x) => x !== si) })}
                      title="Remove leg"
                    />
                  )}
                </div>
              </div>
            ))}
          </div>
          <AddRow
            label="Add leg"
            disabled={alloc.sectors.length >= 8}
            onClick={() => setAt(ai, {
              sectors: [...alloc.sectors, { ...blankSector(), direction: "INBOUND", cabin: defaultCabin ?? "" }],
            })}
          />
        </div>
      ))}
      <AddRow
        label="Add departure"
        disabled={value.length >= MAX_ROWS}
        onClick={() => onChange([...value, blankAllocation()])}
      />
      <p className="text-[10px] text-gray-400">
        A one-off group has a single departure. A series has one per date — that is what makes
        release and utilisation per-departure figures.
      </p>
    </div>
  );
}

// ── Fare components ──────────────────────────────────────────────────────────

export type FareDraft = {
  component_code: string;
  label: string;
  amount_per_pax: string;
  is_guaranteed_until_ticketing: boolean;
  is_refundable_on_noshow: boolean;
};

export const blankFare = (code = "BASE"): FareDraft => ({
  component_code: code, label: "", amount_per_pax: "",
  is_guaranteed_until_ticketing: false, is_refundable_on_noshow: false,
});

/** What a fresh contract starts with — the four lines both reference contracts print. */
export const defaultFareRows = (): FareDraft[] => [
  { ...blankFare("BASE"), is_guaranteed_until_ticketing: true },
  { ...blankFare("YQ"), is_guaranteed_until_ticketing: true },
  { ...blankFare("TAX_STATUTORY"), is_refundable_on_noshow: true },
];

export function FareEditor({
  value, onChange, seats,
}: {
  value: FareDraft[];
  onChange: (v: FareDraft[]) => void;
  seats: number;
}) {
  const setAt = (i: number, patch: Partial<FareDraft>) =>
    onChange(value.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));

  const perPax = value.reduce((sum, r) => sum + (num(r.amount_per_pax) ?? 0), 0);
  const used = new Set(value.map((r) => r.component_code));
  const nextCode = COMPONENT_CODES.find((c) => !used.has(c)) ?? "OT";

  return (
    <div>
      <div className="grid grid-cols-[1fr_1fr_120px_70px_70px_28px] gap-1.5 items-end mb-1">
        <label className={LABEL}>Component</label>
        <label className={LABEL}>Label on the contract</label>
        <label className={LABEL}>Per pax</label>
        <label className={LABEL} title="Frozen until ticketing">Frozen</label>
        <label className={LABEL} title="Refundable when a passenger no-shows">Refund</label>
        <span />
      </div>

      <div className="space-y-1.5">
        {value.map((row, i) => (
          <div key={i} className="grid grid-cols-[1fr_1fr_120px_70px_70px_28px] gap-1.5 items-center">
            <select
              value={row.component_code}
              onChange={(e) => setAt(i, { component_code: e.target.value })}
              className={SMALL_INPUT}
            >
              {COMPONENT_CODES.map((c) => (
                <option key={c} value={c} disabled={c !== row.component_code && used.has(c)}>
                  {COMPONENT_LABEL[c]}
                </option>
              ))}
            </select>
            <input
              value={row.label}
              onChange={(e) => setAt(i, { label: e.target.value })}
              placeholder={COMPONENT_LABEL[row.component_code]}
              className={SMALL_INPUT}
            />
            <input
              type="number"
              step="0.01"
              value={row.amount_per_pax}
              onChange={(e) => setAt(i, { amount_per_pax: e.target.value })}
              placeholder="0.00"
              className={`${SMALL_INPUT} tabular-nums text-right`}
            />
            <div className="flex justify-center">
              <input
                type="checkbox"
                checked={row.is_guaranteed_until_ticketing}
                onChange={(e) => setAt(i, { is_guaranteed_until_ticketing: e.target.checked })}
                className="w-3.5 h-3.5 accent-[#1e3a5f]"
              />
            </div>
            <div className="flex justify-center">
              <input
                type="checkbox"
                checked={row.is_refundable_on_noshow}
                onChange={(e) => setAt(i, { is_refundable_on_noshow: e.target.checked })}
                className="w-3.5 h-3.5 accent-[#1e3a5f]"
              />
            </div>
            {value.length > 1 ? (
              <DeleteCell onClick={() => onChange(value.filter((_, x) => x !== i))} title="Remove component" />
            ) : <span />}
          </div>
        ))}
      </div>

      <AddRow
        label="Add component"
        disabled={value.length >= COMPONENT_CODES.length}
        onClick={() => onChange([...value, blankFare(nextCode)])}
      />

      <div className="mt-3 flex items-center gap-4 text-[11px] border-t border-gray-100 pt-2">
        <span className="text-gray-500">
          Per pax <span className="font-semibold text-gray-800 tabular-nums">{inr(perPax)}</span>
        </span>
        <span className="text-gray-500">
          × {seats || 0} seats ={" "}
          <span className="font-semibold text-gray-800 tabular-nums">{inr(perPax * (seats || 0))}</span>
        </span>
      </div>
      <p className="text-[10px] text-gray-400 mt-1">
        Components are kept apart because a penalty has to name the base it applies to —
        &ldquo;airline retention&rdquo; is base + YQ, while a net-fare penalty is the base alone.
      </p>
    </div>
  );
}

// ── Payment schedule ─────────────────────────────────────────────────────────

export type ScheduleDraft = {
  kind: string;
  due_date: string;
  amount: string;
  pct: string;
  pct_basis: string;
  notes: string;
  /** "" = the contract does not say, "yes" / "no" otherwise. */
  refundable: string;
  /** "N days before departure" when the contract printed no date. */
  due_offset_days: string;
};

export const blankSchedule = (kind = "DEPOSIT"): ScheduleDraft => ({
  kind, due_date: "", amount: "", pct: "", pct_basis: "NET_FARE", notes: "",
  refundable: "", due_offset_days: "",
});

export function ScheduleEditor({
  value, onChange, basisTotals,
}: {
  value: ScheduleDraft[];
  onChange: (v: ScheduleDraft[]) => void;
  /** Contract total per basis, so a percentage can show what it works out to. */
  basisTotals: Record<string, number>;
}) {
  const setAt = (i: number, patch: Partial<ScheduleDraft>) =>
    onChange(value.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));

  const resolved = (row: ScheduleDraft): number | null => {
    const explicit = num(row.amount);
    if (explicit != null) return explicit;
    const pct = num(row.pct);
    if (pct == null || !row.pct_basis) return null;
    return ((basisTotals[row.pct_basis] ?? 0) * pct) / 100;
  };

  const total = value.reduce((sum, r) => sum + (resolved(r) ?? 0), 0);

  return (
    <div>
      <div className="grid grid-cols-[150px_130px_130px_80px_1fr_110px_28px] gap-1.5 items-end mb-1">
        <label className={LABEL}>Instalment</label>
        <label className={LABEL}>Due</label>
        <label className={LABEL}>Amount</label>
        <label className={LABEL}>%</label>
        <label className={LABEL}>of</label>
        <label className={LABEL} title="Is this money returned if the group cancels?">Refundable</label>
        <span />
      </div>

      <div className="space-y-1.5">
        {value.map((row, i) => {
          const computed = num(row.amount) == null ? resolved(row) : null;
          return (
            <div key={i}>
              <div className="grid grid-cols-[150px_130px_130px_80px_1fr_110px_28px] gap-1.5 items-center">
                <select
                  value={row.kind}
                  onChange={(e) => setAt(i, { kind: e.target.value })}
                  className={SMALL_INPUT}
                >
                  {PAYMENT_KINDS.map((k) => (
                    <option key={k} value={k}>{PAYMENT_KIND_LABEL[k]}</option>
                  ))}
                </select>
                <input
                  type="date"
                  value={row.due_date}
                  onChange={(e) => setAt(i, { due_date: e.target.value })}
                  className={SMALL_INPUT}
                />
                <input
                  type="number"
                  step="0.01"
                  value={row.amount}
                  onChange={(e) => setAt(i, { amount: e.target.value })}
                  placeholder={computed != null ? computed.toFixed(2) : "0.00"}
                  className={`${SMALL_INPUT} tabular-nums text-right`}
                />
                <input
                  type="number"
                  step="0.001"
                  value={row.pct}
                  onChange={(e) => setAt(i, { pct: e.target.value })}
                  placeholder="5"
                  className={`${SMALL_INPUT} tabular-nums text-right`}
                />
                <select
                  value={row.pct_basis}
                  onChange={(e) => setAt(i, { pct_basis: e.target.value })}
                  className={SMALL_INPUT}
                >
                  {FARE_BASES.map((b) => (
                    <option key={b} value={b}>{FARE_BASIS_LABEL[b]}</option>
                  ))}
                </select>
                <select
                  value={row.refundable}
                  onChange={(e) => setAt(i, { refundable: e.target.value })}
                  className={SMALL_INPUT}
                >
                  <option value="">Not stated</option>
                  <option value="yes">Refundable</option>
                  <option value="no">Forfeited</option>
                </select>
                {value.length > 1 ? (
                  <DeleteCell onClick={() => onChange(value.filter((_, x) => x !== i))} title="Remove instalment" />
                ) : <span />}
              </div>
              {computed != null && (
                <p className="text-[10px] text-gray-400 pl-[286px] mt-0.5">
                  works out to <span className="tabular-nums font-medium">{inr(computed)}</span>
                </p>
              )}
              {row.due_offset_days && (
                <p className="text-[10px] text-gray-400 pl-[156px] mt-0.5">
                  {row.due_offset_days} days before departure
                  {!row.due_date && " — the date is worked out from the first departure on save"}
                </p>
              )}
            </div>
          );
        })}
      </div>

      <AddRow
        label="Add instalment"
        disabled={value.length >= 12}
        onClick={() => onChange([...value, blankSchedule()])}
      />

      <div className="mt-3 text-[11px] border-t border-gray-100 pt-2 text-gray-500">
        Scheduled <span className="font-semibold text-gray-800 tabular-nums">{inr(total)}</span>
      </div>
      <p className="text-[10px] text-gray-400 mt-1">
        A percentage needs the base it applies to. Deposits are commonly quoted against the
        net fare rather than the total including taxes, and the two give different money.
      </p>
    </div>
  );
}

export const CABIN_OPTIONS = CABINS.map((c) => ({ value: c, label: CABIN_LABEL[c] }));
