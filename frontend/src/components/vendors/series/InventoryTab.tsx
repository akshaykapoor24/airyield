"use client";

/**
 * Inventory: the departures a contract covers, the PNRs held against each, and the names
 * on those PNRs.
 *
 * This is the half the old single-PNR model could not express at all. A departure carries
 * its own seat counts and its own materialisation figure because every quota an airline
 * writes — release, deviation, name replacement — is stated per departure, not per
 * contract.
 */

import { useState } from "react";
import toast from "react-hot-toast";
import {
  ChevronDown, ChevronRight, Loader2, Plane, Plus, Trash2, Users,
} from "lucide-react";

import api from "@/lib/api";
import { apiError } from "@/components/userMaster/shared";
import {
  API_BASE, PAX_TYPES, PAX_TYPE_LABEL,
  type Allocation, type Booking, type ContractDetail,
  inr, materializationTone, routeOf,
} from "@/lib/series";
import { SMALL_INPUT, num } from "./editors";

export default function InventoryTab({
  contract, onChanged,
}: {
  contract: ContractDetail;
  onChanged: (next: ContractDetail) => void;
}) {
  const [open, setOpen] = useState<number[]>(
    contract.allocations.length === 1 ? [contract.allocations[0].id] : [],
  );

  const toggle = (id: number) =>
    setOpen((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const reload = async () => {
    const { data } = await api.get<ContractDetail>(`${API_BASE}/${contract.id}`);
    onChanged(data);
  };

  if (contract.allocations.length === 0) {
    return (
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm py-12 text-center">
        <Plane className="w-7 h-7 text-gray-300 mx-auto mb-2" />
        <p className="text-sm font-medium text-gray-600">No departures yet</p>
        <p className="text-xs text-gray-400 mt-1">
          A contract needs at least one departure before a PNR can hang off it.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {contract.allocations.map((alloc) => (
        <AllocationCard
          key={alloc.id}
          contractId={contract.id}
          allocation={alloc}
          expanded={open.includes(alloc.id)}
          onToggle={() => toggle(alloc.id)}
          onChanged={reload}
        />
      ))}
    </div>
  );
}

function AllocationCard({
  contractId, allocation, expanded, onToggle, onChanged,
}: {
  contractId: number;
  allocation: Allocation;
  expanded: boolean;
  onToggle: () => void;
  onChanged: () => Promise<void>;
}) {
  const [adding, setAdding] = useState(false);
  const [pnr, setPnr] = useState("");
  const [seats, setSeats] = useState("");
  const [tourCode, setTourCode] = useState("");
  const [saving, setSaving] = useState(false);

  const denominator = allocation.firmed_pax ?? allocation.requested_pax ?? 0;

  const addBooking = async () => {
    if (!pnr.trim()) {
      toast.error("A PNR is required — it is how tickets find this booking.");
      return;
    }
    setSaving(true);
    try {
      await api.post(`${API_BASE}/${contractId}/bookings`, {
        allocation_id: allocation.id,
        pnr: pnr.trim(),
        tour_code: tourCode.trim() || null,
        seats: num(seats),
      });
      toast.success(`PNR ${pnr.trim().toUpperCase()} added`);
      setPnr(""); setSeats(""); setTourCode(""); setAdding(false);
      await onChanged();
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSaving(false);
    }
  };

  const removeBooking = async (booking: Booking) => {
    if (!confirm(`Remove PNR ${booking.pnr} from this departure?`)) return;
    try {
      await api.delete(`${API_BASE}/${contractId}/bookings/${booking.id}`);
      toast.success("PNR removed");
      await onChanged();
    } catch (e) {
      toast.error(apiError(e));
    }
  };

  return (
    <section className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-50/60 text-left"
      >
        {expanded ? (
          <ChevronDown className="w-4 h-4 text-gray-400 shrink-0" />
        ) : (
          <ChevronRight className="w-4 h-4 text-gray-400 shrink-0" />
        )}
        <div className="min-w-0">
          <p className="text-xs font-bold text-gray-800">
            {allocation.departure_date ?? "Undated"}
            <span className="ml-2 font-normal text-gray-400">{allocation.allocation_ref}</span>
          </p>
          <p className="text-[11px] text-gray-500 font-mono">{routeOf(allocation.sectors)}</p>
        </div>

        <div className="ml-auto flex items-center gap-5 text-right">
          <Stat label="Seats" value={denominator || "—"} />
          <Stat label="PNRs" value={allocation.bookings.length} />
          <Stat label="Named" value={allocation.named_pax} />
          <Stat label="Ticketed" value={allocation.ticketed_pax} />
          <div>
            <p className="text-[9px] text-gray-400 uppercase tracking-wide">Materialised</p>
            <p className={`text-xs font-bold tabular-nums ${materializationTone(allocation.materialization_pct)}`}>
              {allocation.materialization_pct != null ? `${allocation.materialization_pct}%` : "—"}
            </p>
          </div>
        </div>
      </button>

      {expanded && (
        <div className="border-t border-gray-100">
          {/* legs */}
          {allocation.sectors.length > 0 && (
            <div className="px-4 py-2.5 bg-gray-50/50 border-b border-gray-100">
              <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-1.5">
                Flight legs
              </p>
              <div className="flex flex-wrap gap-2">
                {allocation.sectors.map((s) => (
                  <span
                    key={s.id}
                    className="inline-flex items-center gap-1.5 px-2 py-1 rounded-lg bg-white border border-gray-200 text-[11px]"
                  >
                    <Plane className="w-3 h-3 text-gray-400" />
                    <span className="font-mono font-semibold text-gray-700">
                      {s.origin}→{s.destination}
                    </span>
                    {s.flight_number && <span className="font-mono text-gray-500">{s.flight_number}</span>}
                    {s.rbd && <span className="text-gray-400">/{s.rbd}</span>}
                    {s.departure_at && (
                      <span className="text-gray-400">{s.departure_at.replace("T", " ").slice(0, 16)}</span>
                    )}
                    {s.direction && (
                      <span className="text-[9px] uppercase text-gray-400">{s.direction.toLowerCase()}</span>
                    )}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* bookings */}
          <div className="px-4 py-3">
            <div className="flex items-center gap-2 mb-2">
              <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide">
                PNRs on this departure
              </p>
              <button
                onClick={() => setAdding((v) => !v)}
                className="ml-auto flex items-center gap-1 text-[11px] font-semibold text-[#1e3a5f] hover:bg-gray-50 px-2 py-1 rounded-lg"
              >
                <Plus className="w-3 h-3" /> Add PNR
              </button>
            </div>

            {adding && (
              <div className="grid grid-cols-[160px_100px_1fr_auto_auto] gap-2 items-end mb-3 p-2.5 bg-blue-50/40 rounded-lg border border-blue-100">
                <div>
                  <label className="block text-[10px] font-semibold text-gray-500 uppercase mb-1">PNR</label>
                  <input
                    value={pnr}
                    onChange={(e) => setPnr(e.target.value.toUpperCase())}
                    placeholder="ABC123"
                    className={`${SMALL_INPUT} font-mono uppercase`}
                  />
                </div>
                <div>
                  <label className="block text-[10px] font-semibold text-gray-500 uppercase mb-1">Seats</label>
                  <input
                    type="number"
                    min="1"
                    value={seats}
                    onChange={(e) => setSeats(e.target.value)}
                    className={SMALL_INPUT}
                  />
                </div>
                <div>
                  <label className="block text-[10px] font-semibold text-gray-500 uppercase mb-1">
                    Tour code
                  </label>
                  <input
                    value={tourCode}
                    onChange={(e) => setTourCode(e.target.value.toUpperCase())}
                    placeholder="optional"
                    className={`${SMALL_INPUT} font-mono uppercase`}
                  />
                </div>
                <button
                  onClick={() => setAdding(false)}
                  className="px-3 py-1.5 text-[11px] font-semibold text-gray-500 hover:bg-white rounded-lg"
                >
                  Cancel
                </button>
                <button
                  onClick={addBooking}
                  disabled={saving}
                  className="flex items-center gap-1.5 bg-[#1e3a5f] hover:bg-[#16304f] text-white text-[11px] font-semibold px-3 py-1.5 rounded-lg disabled:opacity-60"
                >
                  {saving && <Loader2 className="w-3 h-3 animate-spin" />} Add
                </button>
              </div>
            )}

            {allocation.bookings.length === 0 ? (
              <p className="text-[11px] text-gray-400 py-4 text-center">
                No PNRs yet. Tickets match to this departure through its PNRs.
              </p>
            ) : (
              <div className="space-y-2">
                {allocation.bookings.map((b) => (
                  <BookingRow
                    key={b.id}
                    contractId={contractId}
                    booking={b}
                    onRemove={() => removeBooking(b)}
                    onChanged={onChanged}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-[9px] text-gray-400 uppercase tracking-wide">{label}</p>
      <p className="text-xs font-bold text-gray-800 tabular-nums">{value}</p>
    </div>
  );
}

function BookingRow({
  contractId, booking, onRemove, onChanged,
}: {
  contractId: number;
  booking: Booking;
  onRemove: () => void;
  onChanged: () => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const numbers = booking.ticket_numbers ?? [];

  return (
    <div className="border border-gray-150 rounded-lg">
      <div className="flex items-center gap-3 px-3 py-2">
        <span className="font-mono text-xs font-bold text-gray-800">{booking.pnr}</span>
        {booking.tour_code && (
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">
            {booking.tour_code}
          </span>
        )}
        <span className="text-[11px] text-gray-500">
          {booking.passengers.length} name{booking.passengers.length !== 1 ? "s" : ""}
        </span>
        <span className="text-[11px] text-gray-500 tabular-nums">
          {booking.tickets_issued} ticketed
          {booking.seats ? <span className="text-gray-400"> / {booking.seats}</span> : null}
        </span>
        <span className="text-[11px] text-gray-600 tabular-nums">{inr(booking.amount_issued)}</span>

        {numbers.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {numbers.slice(0, 3).map((n) => (
              <span
                key={n}
                className="inline-flex px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700 text-[10px] font-mono"
              >
                {n}
              </span>
            ))}
            {numbers.length > 3 && (
              <span
                className="inline-flex px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 text-[10px] font-semibold"
                title={numbers.join(", ")}
              >
                +{numbers.length - 3}
              </span>
            )}
          </div>
        )}

        <div className="ml-auto flex items-center gap-1">
          <button
            onClick={() => setEditing((v) => !v)}
            className="flex items-center gap-1 text-[11px] font-semibold text-[#1e3a5f] hover:bg-gray-50 px-2 py-1 rounded-lg"
          >
            <Users className="w-3 h-3" /> Names
          </button>
          <button onClick={onRemove} className="p-1.5 hover:bg-red-50 rounded-lg" title="Remove PNR">
            <Trash2 className="w-3.5 h-3.5 text-red-400" />
          </button>
        </div>
      </div>

      {editing && (
        <PassengerEditor
          contractId={contractId}
          booking={booking}
          onDone={async () => { setEditing(false); await onChanged(); }}
          onCancel={() => setEditing(false)}
        />
      )}
    </div>
  );
}

type NameDraft = { first_name: string; last_name: string; pax_type: string; ticket_number: string };

function PassengerEditor({
  contractId, booking, onDone, onCancel,
}: {
  contractId: number;
  booking: Booking;
  onDone: () => Promise<void>;
  onCancel: () => void;
}) {
  const [rows, setRows] = useState<NameDraft[]>(
    booking.passengers.length
      ? booking.passengers.map((p) => ({
          first_name: p.first_name ?? "",
          last_name: p.last_name ?? "",
          pax_type: p.pax_type ?? "ADT",
          ticket_number: p.ticket_number ?? "",
        }))
      : [{ first_name: "", last_name: "", pax_type: "ADT", ticket_number: "" }],
  );
  const [saving, setSaving] = useState(false);

  const setAt = (i: number, patch: Partial<NameDraft>) =>
    setRows((prev) => prev.map((r, x) => (x === i ? { ...r, ...patch } : r)));

  // A lap infant takes no seat and counts toward no materialisation floor. Showing the
  // running total here is what makes that visible before it surprises anybody.
  const counting = rows.filter((r) => r.pax_type !== "INF_LAP").length;

  const save = async () => {
    setSaving(true);
    try {
      await api.put(`${API_BASE}/${contractId}/bookings/${booking.id}/passengers`,
        rows
          .filter((r) => r.first_name.trim() || r.last_name.trim())
          .map((r) => ({
            first_name: r.first_name.trim() || null,
            last_name: r.last_name.trim() || null,
            pax_type: r.pax_type,
            ticket_number: r.ticket_number.trim() || null,
            name_status: "named",
          })),
      );
      toast.success("Name list saved");
      await onDone();
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="px-3 py-3 bg-gray-50/60 border-t border-gray-100">
      <div className="grid grid-cols-[1fr_1fr_130px_150px_28px] gap-1.5 mb-1">
        {["First name", "Last name", "Type", "Ticket number", ""].map((h) => (
          <label key={h} className="block text-[10px] font-semibold text-gray-500 uppercase">{h}</label>
        ))}
      </div>
      <div className="space-y-1.5 max-h-72 overflow-y-auto">
        {rows.map((r, i) => (
          <div key={i} className="grid grid-cols-[1fr_1fr_130px_150px_28px] gap-1.5 items-center">
            <input
              value={r.first_name}
              onChange={(e) => setAt(i, { first_name: e.target.value })}
              className={SMALL_INPUT}
            />
            <input
              value={r.last_name}
              onChange={(e) => setAt(i, { last_name: e.target.value })}
              className={SMALL_INPUT}
            />
            <select
              value={r.pax_type}
              onChange={(e) => setAt(i, { pax_type: e.target.value })}
              className={SMALL_INPUT}
            >
              {PAX_TYPES.map((t) => <option key={t} value={t}>{PAX_TYPE_LABEL[t]}</option>)}
            </select>
            <input
              value={r.ticket_number}
              onChange={(e) => setAt(i, { ticket_number: e.target.value })}
              placeholder="optional"
              className={`${SMALL_INPUT} font-mono`}
            />
            <button
              onClick={() => setRows((prev) => prev.filter((_, x) => x !== i))}
              className="p-1.5 hover:bg-red-50 rounded-lg"
              title="Remove name"
            >
              <Trash2 className="w-3.5 h-3.5 text-red-400" />
            </button>
          </div>
        ))}
      </div>

      <div className="flex items-center gap-2 mt-2">
        <button
          onClick={() => setRows((prev) => [...prev, { first_name: "", last_name: "", pax_type: "ADT", ticket_number: "" }])}
          className="flex items-center gap-1 text-[11px] font-semibold text-[#1e3a5f] hover:bg-white px-2 py-1 rounded-lg"
        >
          <Plus className="w-3 h-3" /> Add name
        </button>
        <span className="text-[10px] text-gray-400">
          {counting} of {rows.length} count toward materialisation — a lap infant does not.
        </span>
        <button onClick={onCancel} className="ml-auto px-3 py-1.5 text-[11px] font-semibold text-gray-500 hover:bg-white rounded-lg">
          Cancel
        </button>
        <button
          onClick={save}
          disabled={saving}
          className="flex items-center gap-1.5 bg-[#1e3a5f] hover:bg-[#16304f] text-white text-[11px] font-semibold px-3 py-1.5 rounded-lg disabled:opacity-60"
        >
          {saving && <Loader2 className="w-3 h-3 animate-spin" />} Save names
        </button>
      </div>
    </div>
  );
}
