"use client";

/**
 * Create a Series / SIT / MICE / Group contract, one step at a time.
 *
 * WHY THIS IS NOT ONE FORM. The thing being captured is an airline agreement, and the
 * previous single-screen version of it had eleven fields because it could only describe
 * the very simplest contract — one PNR, one date, one fare. A real one carries several
 * departures, several flight legs, a fare split into components, an instalment plan, and
 * the terms that price every change, and forty fields on one screen is not a form anybody
 * fills in correctly.
 *
 * TWO WAYS IN. Typed by hand from the list screen (a modal), or seeded from a contract PDF
 * the AI has read (the /new page, beside the PDF). A seeded wizard shows what was read and
 * from where — the violet page badges — and lists what the reader was unsure of; those
 * warnings must be ticked off before the contract can be saved. Nothing the AI read is
 * saved until a person has looked at it.
 *
 * Each step saves nothing on its own; the whole graph goes up in one POST at the end, so
 * an abandoned wizard leaves no half-contract behind. Only step 1 is required — the rest
 * can be filled in later on the contract's own screen.
 */

import { useMemo, useState } from "react";
import toast from "react-hot-toast";
import {
  AlertTriangle, ArrowLeft, ArrowRight, Check, ChevronDown, ChevronUp, Info, Layers,
  Loader2, Sparkles, X,
} from "lucide-react";

import api from "@/lib/api";
import { apiError } from "@/components/userMaster/shared";
import AirlinePicker from "@/components/tickets/AirlinePicker";
import SearchSelect from "@/components/ui/SearchSelect";
import { requireFields } from "@/lib/requiredFields";
import {
  API_BASE, CABINS, CABIN_LABEL, CONTRACT_TYPES, CONTRACT_TYPE_HINT,
  CONTRACT_TYPE_LABEL, COMPONENT_LABEL, DEADLINE_TYPE_LABEL, FARE_BASIS_LABEL,
  PAYMENT_KIND_LABEL, TERM_RULE_LABEL, inr,
  type DraftWarning, type Evidence, type ExtractionDraft,
} from "@/lib/series";
import {
  AllocationsEditor, FareEditor, INPUT, LABEL, ScheduleEditor,
  blankAllocation, blankFare, blankSchedule, blankSector, defaultFareRows, num,
  type AllocationDraft, type FareDraft, type ScheduleDraft,
} from "./editors";
import {
  AiMark, DeadlineRulesEditor, PassengerListEditor, TermsEditor, draftToTerm, termToDraft,
  type DeadlineDraft, type PassengerDraft, type TermDraft,
} from "./termsEditors";

const STEPS = ["Contract", "Departures", "Fare", "Payment", "Terms", "Passengers", "Review"] as const;

type Header = {
  contract_type: string;
  contract_number: string;
  group_reference: string;
  group_name: string;
  source_type: string;
  agent_name: string;
  supplier_ref: string;
  airline_code: string;
  airline_name: string;
  currency: string;
  contracted_pax: string;
  minimum_pax: string;
  materialization_floor_pct: string;
  cabin: string;
  contract_date: string;
  option_expires_on: string;
  foc_per_paid: string;
  baggage_allowance: string;
  event_name: string;
  notes: string;
};

const BLANK: Header = {
  contract_type: "GROUP",
  contract_number: "",
  group_reference: "",
  group_name: "",
  source_type: "AIRLINE",
  agent_name: "",
  supplier_ref: "",
  airline_code: "",
  airline_name: "",
  currency: "INR",
  contracted_pax: "",
  minimum_pax: "",
  materialization_floor_pct: "",
  cabin: "ECONOMY",
  contract_date: "",
  option_expires_on: "",
  foc_per_paid: "",
  baggage_allowance: "",
  event_name: "",
  notes: "",
};

/** Which wizard step a warning's field path belongs to. */
const stepOf = (field?: string | null): number | null => {
  if (!field) return null;
  if (field.startsWith("header")) return 0;
  if (field.startsWith("allocations")) return 1;
  if (field.startsWith("fare_components")) return 2;
  if (field.startsWith("payment_schedule")) return 3;
  if (field.startsWith("terms") || field.startsWith("deadlines")) return 4;
  if (field.startsWith("passengers")) return 5;
  return null;
};

const s = (v: unknown) => (v == null ? "" : String(v));
/** "2023-12-27T01:05" for a datetime-local input, from whatever the server sent. */
const localDateTime = (v: unknown) => (v ? String(v).slice(0, 16) : "");

type Seeded = {
  head: Header;
  allocations: AllocationDraft[];
  fare: FareDraft[];
  schedule: ScheduleDraft[];
  terms: TermDraft[];
  deadlines: DeadlineDraft[];
  passengers: PassengerDraft[];
  pnr: string;
};

/** The wizard's string-typed state, from what the AI read. */
function fromDraft(draft: ExtractionDraft): Seeded {
  const h = draft.header ?? {};
  const head: Header = { ...BLANK };
  (Object.keys(BLANK) as (keyof Header)[]).forEach((k) => {
    if (h[k] != null && h[k] !== "") head[k] = String(h[k]);
  });
  head.cabin = head.cabin || "ECONOMY";
  head.currency = head.currency || "INR";

  const allocations: AllocationDraft[] = (draft.allocations ?? []).map((a, i) => ({
    allocation_ref: `A${i + 1}`,
    departure_date: s(a.departure_date),
    requested_pax: s(a.requested_pax),
    firmed_pax: "",
    sectors: (a.sectors?.length ? a.sectors : [{}]).map((x) => ({
      ...blankSector(),
      direction: s(x.direction) || "OUTBOUND",
      origin: s(x.origin),
      destination: s(x.destination),
      airline_code: s(x.airline_code),
      flight_number: s(x.flight_number),
      departure_at: localDateTime(x.departure_at),
      arrival_at: localDateTime(x.arrival_at),
      cabin: s(x.cabin),
      rbd: s(x.rbd),
    })),
  }));

  const fare: FareDraft[] = (draft.fare_components ?? []).map((c) => ({
    ...blankFare(c.component_code ?? "BASE"),
    label: s(c.label),
    amount_per_pax: s(c.amount_per_pax),
    is_guaranteed_until_ticketing: !!c.is_guaranteed_until_ticketing,
    is_refundable_on_noshow: !!c.is_refundable_on_noshow,
  }));

  const schedule: ScheduleDraft[] = (draft.payment_schedule ?? []).map((p) => ({
    ...blankSchedule(p.kind ?? "DEPOSIT"),
    due_date: s(p.due_date),
    amount: s(p.amount),
    pct: s(p.pct),
    pct_basis: s(p.pct_basis) || "NET_FARE",
    notes: s(p.notes),
    refundable: p.is_refundable == null ? "" : p.is_refundable ? "yes" : "no",
    due_offset_days: s(p.due_offset_days),
  }));

  const deadlines: DeadlineDraft[] = (draft.deadlines ?? [])
    // The offer's expiry is a header field; the server raises its deadline from there.
    .filter((d) => d.deadline_type !== "OPTION_EXPIRY")
    .map((d) => ({
      deadline_type: s(d.deadline_type),
      offset_days: s(d.offset_days),
      offset_hours: s(d.offset_hours),
      stated_date: s(d.stated_date),
      action_required: s(d.action_required),
    }));

  const passengers: PassengerDraft[] = (draft.passengers ?? []).map((p) => ({
    title: s(p.title), first_name: s(p.first_name), last_name: s(p.last_name),
    pax_type: s(p.pax_type) || "ADT", gender: s(p.gender), date_of_birth: s(p.date_of_birth),
    nationality: s(p.nationality), passport_number: s(p.passport_number),
    passport_expiry: s(p.passport_expiry),
  }));

  // An airline group reference like L64E9A IS the group PNR; a request id is not.
  const ref = head.group_reference.replace(/[^A-Za-z0-9]/g, "");
  return {
    head,
    allocations: allocations.length ? allocations : [blankAllocation()],
    fare: fare.length ? fare : defaultFareRows(),
    schedule: schedule.length ? schedule : [blankSchedule("ADVANCE_DEPOSIT")],
    terms: (draft.terms ?? []).map(termToDraft),
    deadlines,
    passengers,
    pnr: /^[A-Z0-9]{6}$/i.test(ref) ? ref.toUpperCase() : "",
  };
}

export default function ContractWizard({
  onClose, onSaved, seed = null, documentId = null, layout = "modal", onJump,
}: {
  onClose: () => void;
  onSaved: (id: number) => void;
  /** What the AI read from an uploaded PDF. */
  seed?: ExtractionDraft | null;
  /** The uploaded PDF — linked to the contract on save, whether or not it was read. */
  documentId?: number | null;
  layout?: "modal" | "page";
  /** Turn the PDF beside the form to a page. */
  onJump?: (page: number) => void;
}) {
  const initial = useMemo(() => (seed ? fromDraft(seed) : null), [seed]);
  const evidence: Evidence | null = seed?.evidence ?? null;
  const warnings: DraftWarning[] = useMemo(() => seed?.warnings ?? [], [seed]);

  const [step, setStep] = useState(0);
  const [head, setHead] = useState<Header>(initial?.head ?? BLANK);
  const [allocations, setAllocations] = useState<AllocationDraft[]>(initial?.allocations ?? [blankAllocation()]);
  const [fare, setFare] = useState<FareDraft[]>(initial?.fare ?? defaultFareRows());
  const [schedule, setSchedule] = useState<ScheduleDraft[]>(initial?.schedule ?? [blankSchedule("ADVANCE_DEPOSIT")]);
  const [terms, setTerms] = useState<TermDraft[]>(initial?.terms ?? []);
  const [deadlines, setDeadlines] = useState<DeadlineDraft[]>(initial?.deadlines ?? []);
  const [passengers, setPassengers] = useState<PassengerDraft[]>(initial?.passengers ?? []);
  const [pnr, setPnr] = useState(initial?.pnr ?? "");
  const [paxDeparture, setPaxDeparture] = useState(0);
  const [acknowledged, setAcknowledged] = useState(false);
  const [showWarnings, setShowWarnings] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [suppliers, setSuppliers] = useState<string[]>([]);

  const isB2B = head.source_type === "B2B";
  const set = <K extends keyof Header>(k: K, v: Header[K]) => setHead((p) => ({ ...p, [k]: v }));
  const mark = (path: string) => <AiMark path={path} evidence={evidence} onJump={onJump} />;

  const mustAcknowledge = warnings.some((w) => w.level !== "info");
  const warningsByStep = useMemo(() => {
    const out: Record<number, number> = {};
    warnings.forEach((w) => {
      const at = stepOf(w.field);
      if (at != null && w.level !== "info") out[at] = (out[at] ?? 0) + 1;
    });
    return out;
  }, [warnings]);

  // Seats the contract is priced over: the sum of its departures, falling back to the
  // header figure while no departure has been entered yet.
  const seats = useMemo(() => {
    const fromAllocations = allocations.reduce(
      (sum, a) => sum + (num(a.firmed_pax) ?? num(a.requested_pax) ?? 0), 0,
    );
    return fromAllocations || (num(head.contracted_pax) ?? 0);
  }, [allocations, head.contracted_pax]);

  /** Contract totals per basis, so a percentage instalment can show its money. */
  const basisTotals = useMemo(() => {
    const amount = (code: string) =>
      fare.filter((f) => f.component_code === code)
        .reduce((sum, f) => sum + (num(f.amount_per_pax) ?? 0), 0);
    const all = fare.reduce((sum, f) => sum + (num(f.amount_per_pax) ?? 0), 0);
    return {
      NET_FARE: amount("BASE") * seats,
      AI_RETENTION: (amount("BASE") + amount("YQ")) * seats,
      FARE_PLUS_SURCHARGES:
        (amount("BASE") + amount("YQ") + amount("YR_I") + amount("YR_F")) * seats,
      TOTAL: all * seats,
      TAX_ONLY: amount("TAX_STATUTORY") * seats,
    } as Record<string, number>;
  }, [fare, seats]);

  const perPax = fare.reduce((sum, f) => sum + (num(f.amount_per_pax) ?? 0), 0);

  const loadSuppliers = async () => {
    if (suppliers.length) return;
    try {
      const { data } = await api.get<{ id: number; name: string }[]>("/suppliers/", {
        params: { limit: 5000 },
      });
      setSuppliers(data.map((x) => x.name).filter(Boolean));
    } catch {
      /* the field allows a typed value, so a failed list is not fatal */
    }
  };

  const validateHeader = (): boolean =>
    requireFields([
      { label: "Contract Type", value: head.contract_type },
      { label: "Contract Number", value: head.contract_number },
      { label: "Supplier", value: head.agent_name, when: isB2B },
    ], "the contract step");

  const next = () => {
    if (step === 0 && !validateHeader()) return;
    setError("");
    setStep((x) => Math.min(x + 1, STEPS.length - 1));
  };

  const namedPassengers = passengers.filter((p) => p.first_name.trim() || p.last_name.trim());

  const save = async () => {
    if (!validateHeader()) { setStep(0); return; }
    if (mustAcknowledge && !acknowledged) {
      setShowWarnings(true);
      toast.error("Tick “I have checked these” after reviewing what the AI flagged.");
      return;
    }
    if (namedPassengers.length && !pnr.trim()) {
      setStep(5);
      toast.error("Passengers are filed under a PNR — enter the group PNR, or remove the names and add them later.");
      return;
    }
    setSaving(true); setError("");
    try {
      const payload = {
        contract_type: head.contract_type,
        contract_number: head.contract_number.trim() || null,
        group_reference: head.group_reference.trim() || null,
        group_name: head.group_name.trim() || null,
        source_type: head.source_type,
        // On an AIRLINE contract the server mirrors the airline into agent_name.
        agent_name: isB2B ? head.agent_name.trim() || null : null,
        supplier_ref: isB2B ? head.supplier_ref.trim() || null : null,
        airline_code: head.airline_code.trim() || null,
        airline_name: head.airline_name.trim() || null,
        currency: head.currency.trim().toUpperCase() || "INR",
        contracted_pax: num(head.contracted_pax),
        minimum_pax: num(head.minimum_pax),
        materialization_floor_pct: num(head.materialization_floor_pct),
        cabin: head.cabin || null,
        contract_date: head.contract_date || null,
        option_expires_on: head.option_expires_on || null,
        foc_per_paid: num(head.foc_per_paid),
        baggage_allowance: head.baggage_allowance.trim() || null,
        event_name: head.event_name.trim() || null,
        travel_from: firstDate(allocations),
        travel_to: lastDate(allocations),
        status: "active",
        notes: head.notes.trim() || null,
        allocations: allocations
          .filter((a) => a.departure_date || a.requested_pax || a.sectors.some((x) => x.origin))
          .map((a, i) => ({
            allocation_ref: a.allocation_ref.trim() || `A${i + 1}`,
            departure_date: a.departure_date || null,
            requested_pax: num(a.requested_pax),
            firmed_pax: num(a.firmed_pax),
            sectors: a.sectors
              .filter((x) => x.origin || x.destination || x.flight_number)
              .map((x, si) => ({
                segment_no: si + 1,
                direction: x.direction || null,
                origin: x.origin || null,
                destination: x.destination || null,
                airline_code: (x.airline_code || head.airline_code).trim() || null,
                flight_number: x.flight_number || null,
                departure_at: x.departure_at || null,
                arrival_at: x.arrival_at || null,
                cabin: x.cabin || head.cabin || null,
                rbd: x.rbd || null,
                allocated_pax: num(a.requested_pax),
              })),
          })),
        fare_components: fare
          .filter((f) => num(f.amount_per_pax) != null)
          .map((f, i) => ({
            component_code: f.component_code,
            label: f.label.trim() || null,
            amount_per_pax: num(f.amount_per_pax),
            is_guaranteed_until_ticketing: f.is_guaranteed_until_ticketing,
            is_refundable_on_noshow: f.is_refundable_on_noshow,
            sort_order: i,
          })),
        payment_schedule: schedule
          .filter((x) => x.due_date || num(x.amount) != null || num(x.pct) != null || x.due_offset_days)
          .map((x, i) => ({
            kind: x.kind,
            seq: i + 1,
            due_date: x.due_date || null,
            amount: num(x.amount),
            pct: num(x.pct),
            pct_basis: x.pct_basis || null,
            notes: x.notes.trim() || null,
            is_refundable: x.refundable === "" ? null : x.refundable === "yes",
            due_offset_days: num(x.due_offset_days),
          })),
        deadlines: deadlines
          .filter((d) => d.offset_days || d.offset_hours || d.stated_date)
          .map((d) => ({
            deadline_type: d.deadline_type,
            anchor: "DEPARTURE",
            offset_days: num(d.offset_days),
            offset_hours: num(d.offset_hours),
            stated_date: d.stated_date || null,
            action_required: d.action_required.trim() || null,
          })),
        terms: terms.map(draftToTerm),
        bookings: pnr.trim()
          ? [{
            allocation_index: paxDeparture,
            pnr: pnr.trim().toUpperCase(),
            seats: num(allocations[paxDeparture]?.requested_pax ?? "") ?? null,
            passengers: namedPassengers.map((p) => ({
              title: p.title.trim() || null,
              first_name: p.first_name.trim() || null,
              last_name: p.last_name.trim() || null,
              pax_type: p.pax_type || "ADT",
              gender: p.gender || null,
              date_of_birth: p.date_of_birth || null,
              nationality: p.nationality.trim() || null,
              passport_number: p.passport_number.trim() || null,
              passport_expiry: p.passport_expiry || null,
            })),
          }]
          : [],
        document_id: documentId,
      };

      const { data } = await api.post<{ id: number }>(`${API_BASE}/`, payload);
      toast.success("Contract created");
      onSaved(data.id);
    } catch (e) {
      const message = apiError(e);
      setError(message);
      toast.error(message, { duration: 5000 });
    } finally {
      setSaving(false);
    }
  };

  const body = (
    <>
      {/* steps */}
      <div className="flex items-center gap-1 px-5 py-3 border-b border-gray-100 overflow-x-auto">
        {STEPS.map((title, i) => (
          <button
            key={title}
            type="button"
            onClick={() => (i <= step || validateHeader()) && setStep(i)}
            className={`relative flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-semibold whitespace-nowrap ${
              i === step
                ? "bg-[#1e3a5f] text-white"
                : i < step
                  ? "text-emerald-700 hover:bg-emerald-50"
                  : "text-gray-400 hover:bg-gray-50"
            }`}
          >
            <span
              className={`w-4 h-4 rounded-full grid place-items-center text-[9px] ${
                i < step ? "bg-emerald-100 text-emerald-700" : i === step ? "bg-white/20" : "bg-gray-100"
              }`}
            >
              {i < step ? <Check className="w-2.5 h-2.5" /> : i + 1}
            </span>
            {title}
            {warningsByStep[i] ? (
              <span className="w-1.5 h-1.5 rounded-full bg-amber-500" title={`${warningsByStep[i]} to check`} />
            ) : null}
          </button>
        ))}
      </div>

      <div className="px-5 py-4 overflow-y-auto flex-1 min-h-0">
        {seed && (
          <ReadBanner
            summary={seed.summary}
            warnings={warnings}
            open={showWarnings}
            onToggle={() => setShowWarnings((v) => !v)}
            onGo={(w) => { const at = stepOf(w.field); if (at != null) setStep(at); }}
            mustAcknowledge={mustAcknowledge}
            acknowledged={acknowledged}
            onAcknowledge={setAcknowledged}
          />
        )}

        {step === 0 && (
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={LABEL}>Contract Type <span className="text-red-400">*</span>{mark("header.contract_type")}</label>
              <select value={head.contract_type} onChange={(e) => set("contract_type", e.target.value)} className={INPUT}>
                {CONTRACT_TYPES.map((t) => <option key={t} value={t}>{CONTRACT_TYPE_LABEL[t]}</option>)}
              </select>
              <p className="text-[10px] text-gray-400 mt-1">{CONTRACT_TYPE_HINT[head.contract_type]}</p>
            </div>

            <div>
              <label className={LABEL}>Bought from{mark("header.source_type")}</label>
              <select
                value={head.source_type}
                onChange={(e) => { set("source_type", e.target.value); set("agent_name", ""); }}
                onFocus={loadSuppliers}
                className={INPUT}
              >
                <option value="AIRLINE">Airline</option>
                <option value="B2B">B2B / consolidator</option>
              </select>
            </div>

            <div>
              <label className={LABEL}>
                Contract / Request No. <span className="text-red-400">*</span>{mark("header.contract_number")}
              </label>
              <input value={head.contract_number} onChange={(e) => set("contract_number", e.target.value)}
                placeholder="GRP123003" className={`${INPUT} font-mono`} />
            </div>

            <div>
              <label className={LABEL}>Group reference / PNR{mark("header.group_reference")}</label>
              <input value={head.group_reference} onChange={(e) => set("group_reference", e.target.value)}
                placeholder="L64E9A" className={`${INPUT} font-mono`} />
            </div>

            <div className="col-span-2">
              <label className={LABEL}>Group name{mark("header.group_name")}</label>
              <input value={head.group_name} onChange={(e) => set("group_name", e.target.value)}
                placeholder="DELATQDEL" className={INPUT} />
            </div>

            {isB2B && (
              <>
                <div>
                  <label className={LABEL}>Supplier <span className="text-red-400">*</span>{mark("header.supplier_name")}</label>
                  <SearchSelect value={head.agent_name} options={suppliers}
                    onChange={(v) => set("agent_name", v)} placeholder="Search suppliers…" allowCustom />
                </div>
                <div>
                  <label className={LABEL}>Supplier reference{mark("header.supplier_ref")}</label>
                  <input value={head.supplier_ref} onChange={(e) => set("supplier_ref", e.target.value)}
                    className={`${INPUT} font-mono`} />
                </div>
              </>
            )}

            <div className="col-span-2">
              <label className={LABEL}>Airline{mark("header.airline_code")}</label>
              <AirlinePicker
                code={head.airline_code}
                name={head.airline_name}
                onCodeChange={(v) => set("airline_code", v)}
                onPick={(a) => {
                  set("airline_code", a.iata_code ?? "");
                  set("airline_name", a.name ?? "");
                }}
              />
              <p className="text-[10px] text-gray-400 mt-1">
                Filled either way — a block bought from a consolidator still flies on
                somebody&apos;s metal.
              </p>
            </div>

            <div>
              <label className={LABEL}>Cabin{mark("header.cabin")}</label>
              <select value={head.cabin} onChange={(e) => set("cabin", e.target.value)} className={INPUT}>
                {CABINS.map((c) => <option key={c} value={c}>{CABIN_LABEL[c]}</option>)}
              </select>
              <p className="text-[10px] text-gray-400 mt-1">
                One cabin per contract — per-cabin penalty grids are priced for this cabin.
              </p>
            </div>

            <div>
              <label className={LABEL}>Currency{mark("header.currency")}</label>
              <input value={head.currency} maxLength={3}
                onChange={(e) => set("currency", e.target.value.toUpperCase())}
                className={`${INPUT} font-mono uppercase`} />
            </div>

            <div>
              <label className={LABEL}>Contract date{mark("header.contract_date")}</label>
              <input type="date" value={head.contract_date} onChange={(e) => set("contract_date", e.target.value)} className={INPUT} />
            </div>

            <div>
              <label className={LABEL} title="The date an unaccepted offer lapses">
                Offer valid until{mark("header.option_expires_on")}
              </label>
              <input type="date" value={head.option_expires_on} onChange={(e) => set("option_expires_on", e.target.value)} className={INPUT} />
            </div>

            <div>
              <label className={LABEL}>Contracted pax{mark("header.contracted_pax")}</label>
              <input type="number" min="1" value={head.contracted_pax}
                onChange={(e) => set("contracted_pax", e.target.value)} placeholder="60" className={INPUT} />
            </div>

            <div>
              <label className={LABEL}>Minimum pax{mark("header.minimum_pax")}</label>
              <input type="number" min="1" value={head.minimum_pax}
                onChange={(e) => set("minimum_pax", e.target.value)} placeholder="10" className={INPUT} />
            </div>

            <div>
              <label className={LABEL} title="Share of the firmed group that must travel">
                Materialisation floor %{mark("header.materialization_floor_pct")}
              </label>
              <input type="number" min="0" max="100" value={head.materialization_floor_pct}
                onChange={(e) => set("materialization_floor_pct", e.target.value)} placeholder="80" className={INPUT} />
            </div>

            <div>
              <label className={LABEL} title="One free tour-conductor seat per this many paid">
                FOC — 1 free per{mark("header.foc_per_paid")}
              </label>
              <input type="number" min="1" value={head.foc_per_paid}
                onChange={(e) => set("foc_per_paid", e.target.value)} placeholder="—" className={INPUT} />
            </div>

            <div>
              <label className={LABEL}>Baggage{mark("header.baggage_allowance")}</label>
              <input value={head.baggage_allowance} onChange={(e) => set("baggage_allowance", e.target.value)}
                placeholder="2PC / 23KG" className={INPUT} />
            </div>

            {(head.contract_type === "MICE" || head.contract_type === "SIT" || head.event_name) && (
              <div>
                <label className={LABEL}>Event / purpose{mark("header.event_name")}</label>
                <input value={head.event_name} onChange={(e) => set("event_name", e.target.value)}
                  placeholder="Dealer conference, Goa" className={INPUT} />
              </div>
            )}

            <div className="col-span-2">
              <label className={LABEL}>Notes</label>
              <textarea value={head.notes} onChange={(e) => set("notes", e.target.value)} rows={2} className={INPUT} />
            </div>
          </div>
        )}

        {step === 1 && (
          <>
            <SectionMark label="Departures" path="allocations" mark={mark} />
            <AllocationsEditor value={allocations} onChange={setAllocations} defaultCabin={head.cabin} />
          </>
        )}

        {step === 2 && (
          <>
            <SectionMark label="Fare per passenger" path="fare_components" mark={mark} />
            <FareEditor value={fare} onChange={setFare} seats={seats} />
          </>
        )}

        {step === 3 && (
          <>
            <SectionMark label="Deposits and payments" path="payment_schedule" mark={mark} />
            <ScheduleEditor value={schedule} onChange={setSchedule} basisTotals={basisTotals} />
          </>
        )}

        {step === 4 && (
          <div className="space-y-5">
            <section>
              <SectionMark label="Deadlines" path="deadlines" mark={mark} />
              <DeadlineRulesEditor value={deadlines} onChange={setDeadlines} />
            </section>
            <section>
              <SectionMark label="Cancellation, release and change terms" path="terms" mark={mark} />
              <TermsEditor value={terms} onChange={setTerms} onJump={onJump} />
            </section>
          </div>
        )}

        {step === 5 && (
          <div className="space-y-3">
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className={LABEL}>Group PNR</label>
                <input value={pnr} onChange={(e) => setPnr(e.target.value.toUpperCase())}
                  placeholder="L64E9A" className={`${INPUT} font-mono uppercase`} />
              </div>
              {allocations.length > 1 && (
                <div>
                  <label className={LABEL}>Departure</label>
                  <select value={paxDeparture} onChange={(e) => setPaxDeparture(Number(e.target.value))} className={INPUT}>
                    {allocations.map((a, i) => (
                      <option key={i} value={i}>{a.departure_date || `Departure ${i + 1}`}</option>
                    ))}
                  </select>
                </div>
              )}
            </div>
            <p className="text-[10px] text-gray-400">
              Optional. The PNR is how issued tickets are matched back to this contract. Names can
              be added now or later from the contract&apos;s Inventory tab — the name-list deadline
              reminds you either way.
            </p>
            <SectionMark label={`Passengers (${namedPassengers.length})`} path="passengers" mark={mark} />
            <PassengerListEditor value={passengers} onChange={setPassengers} />
          </div>
        )}

        {step === 6 && (
          <Review
            head={head}
            allocations={allocations}
            fare={fare}
            schedule={schedule}
            terms={terms}
            deadlines={deadlines}
            passengers={namedPassengers.length}
            pnr={pnr}
            seats={seats}
            perPax={perPax}
            basisTotals={basisTotals}
          />
        )}

        {error && <p className="text-xs text-red-500 mt-3">{error}</p>}
      </div>

      <div className="flex items-center gap-2 px-5 py-3 border-t border-gray-100">
        {step > 0 && (
          <button
            onClick={() => setStep((x) => x - 1)}
            className="flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold text-gray-600 hover:bg-gray-50 rounded-lg"
          >
            <ArrowLeft className="w-3.5 h-3.5" /> Back
          </button>
        )}
        <button
          onClick={onClose}
          className="ml-auto px-3.5 py-2 text-xs font-semibold text-gray-500 hover:bg-gray-50 rounded-lg"
        >
          Cancel
        </button>
        {step < STEPS.length - 1 ? (
          <button
            onClick={next}
            className="flex items-center gap-1.5 bg-[#1e3a5f] hover:bg-[#16304f] text-white text-xs font-semibold px-3.5 py-2 rounded-lg"
          >
            Next <ArrowRight className="w-3.5 h-3.5" />
          </button>
        ) : (
          <button
            onClick={save}
            disabled={saving || (mustAcknowledge && !acknowledged)}
            title={mustAcknowledge && !acknowledged ? "Review the flagged items first" : undefined}
            className="flex items-center gap-1.5 bg-[#1e3a5f] hover:bg-[#16304f] text-white text-xs font-semibold px-3.5 py-2 rounded-lg disabled:opacity-60"
          >
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            Create contract
          </button>
        )}
      </div>
    </>
  );

  if (layout === "page") {
    return (
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm flex flex-col h-full min-h-0">
        {body}
      </div>
    );
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-5xl max-h-[92vh] flex flex-col">
        <div className="flex items-center gap-2 px-5 py-3 rounded-t-xl" style={{ background: "#1e3a5f" }}>
          <Layers className="w-4 h-4 text-white" />
          <h2 className="text-sm font-bold text-white">Add contract</h2>
          <button onClick={onClose} className="ml-auto p-1 hover:bg-white/10 rounded-lg">
            <X className="w-4 h-4 text-white" />
          </button>
        </div>
        {body}
      </div>
    </div>
  );
}

function SectionMark({ label, path, mark }: { label: string; path: string; mark: (p: string) => React.ReactNode }) {
  return (
    <p className="text-[11px] font-bold text-gray-700 uppercase tracking-wide mb-2">
      {label}{mark(path)}
    </p>
  );
}

/** What the AI made of the document, and what it wants a person to check. */
function ReadBanner({
  summary, warnings, open, onToggle, onGo, mustAcknowledge, acknowledged, onAcknowledge,
}: {
  summary?: string | null;
  warnings: DraftWarning[];
  open: boolean;
  onToggle: () => void;
  onGo: (w: DraftWarning) => void;
  mustAcknowledge: boolean;
  acknowledged: boolean;
  onAcknowledge: (v: boolean) => void;
}) {
  const serious = warnings.filter((w) => w.level !== "info");
  return (
    <div className="mb-4 rounded-lg border border-violet-100 bg-violet-50/40">
      <button type="button" onClick={onToggle} className="w-full flex items-start gap-2 px-3 py-2 text-left">
        <Sparkles className="w-3.5 h-3.5 text-violet-600 mt-0.5 shrink-0" />
        <span className="flex-1 min-w-0">
          <span className="block text-[11px] font-semibold text-violet-800">
            Filled from the uploaded contract — review every step before saving
            {serious.length > 0 && (
              <span className="ml-2 text-amber-700">
                · {serious.length} item{serious.length !== 1 ? "s" : ""} to check
              </span>
            )}
          </span>
          {summary && <span className="block text-[11px] text-gray-600 mt-0.5">{summary}</span>}
        </span>
        {open ? <ChevronUp className="w-3.5 h-3.5 text-gray-400" /> : <ChevronDown className="w-3.5 h-3.5 text-gray-400" />}
      </button>
      {open && warnings.length > 0 && (
        <div className="px-3 pb-2.5 space-y-1">
          {warnings.map((w, i) => {
            const clickable = stepOf(w.field) != null;
            return (
              <button
                type="button"
                key={i}
                onClick={() => clickable && onGo(w)}
                className={`w-full flex items-start gap-1.5 text-left text-[11px] rounded px-1.5 py-1 ${
                  clickable ? "hover:bg-white" : "cursor-default"
                }`}
              >
                {w.level === "info"
                  ? <Info className="w-3 h-3 text-blue-400 mt-0.5 shrink-0" />
                  : <AlertTriangle className="w-3 h-3 text-amber-500 mt-0.5 shrink-0" />}
                <span className={w.level === "info" ? "text-gray-500" : "text-gray-800"}>{w.message}</span>
              </button>
            );
          })}
          {mustAcknowledge && (
            <label className="flex items-center gap-1.5 text-[11px] font-semibold text-gray-700 pt-1.5 px-1.5">
              <input type="checkbox" checked={acknowledged} onChange={(e) => onAcknowledge(e.target.checked)}
                className="w-3.5 h-3.5 accent-[#1e3a5f]" />
              I have checked these against the document
            </label>
          )}
        </div>
      )}
    </div>
  );
}

const firstDate = (rows: AllocationDraft[]): string | null => {
  const dates = rows.map((a) => a.departure_date).filter(Boolean).sort();
  return dates[0] || null;
};
const lastDate = (rows: AllocationDraft[]): string | null => {
  const dates = rows.map((a) => a.departure_date).filter(Boolean).sort();
  return dates[dates.length - 1] || null;
};

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-2 text-[11px]">
      <span className="text-gray-400 w-36 shrink-0">{label}</span>
      <span className="text-gray-800 font-medium">{value}</span>
    </div>
  );
}

function Review({
  head, allocations, fare, schedule, terms, deadlines, passengers, pnr, seats, perPax, basisTotals,
}: {
  head: Header;
  allocations: AllocationDraft[];
  fare: FareDraft[];
  schedule: ScheduleDraft[];
  terms: TermDraft[];
  deadlines: DeadlineDraft[];
  passengers: number;
  pnr: string;
  seats: number;
  perPax: number;
  basisTotals: Record<string, number>;
}) {
  const priced = fare.filter((f) => num(f.amount_per_pax) != null);
  const instalments = schedule.filter((x) => x.due_date || num(x.amount) != null || num(x.pct) != null);
  const departures = allocations.filter((a) => a.departure_date || a.sectors.some((x) => x.origin));
  const byRule = terms.reduce<Record<string, number>>((acc, t) => {
    acc[t.rule_type] = (acc[t.rule_type] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="space-y-4">
      <section>
        <p className="text-[11px] font-bold text-gray-700 uppercase tracking-wide mb-2">Contract</p>
        <div className="space-y-1">
          <Row label="Type" value={CONTRACT_TYPE_LABEL[head.contract_type]} />
          <Row label="Number" value={head.contract_number || "—"} />
          {head.group_reference && <Row label="Group reference" value={head.group_reference} />}
          {head.group_name && <Row label="Group name" value={head.group_name} />}
          <Row
            label="Counterparty"
            value={head.source_type === "B2B" ? head.agent_name || "—" : head.airline_name || head.airline_code || "—"}
          />
          <Row label="Cabin" value={CABIN_LABEL[head.cabin] ?? head.cabin} />
          {head.minimum_pax && <Row label="Minimum group" value={`${head.minimum_pax} pax`} />}
          {head.materialization_floor_pct && <Row label="Materialisation floor" value={`${head.materialization_floor_pct}%`} />}
          {head.option_expires_on && <Row label="Offer valid until" value={head.option_expires_on} />}
        </div>
      </section>

      <section>
        <p className="text-[11px] font-bold text-gray-700 uppercase tracking-wide mb-2">
          Departures ({departures.length})
        </p>
        {departures.length === 0 ? (
          <p className="text-[11px] text-gray-400">None yet — you can add them on the contract afterwards.</p>
        ) : (
          <div className="space-y-1">
            {departures.map((a, i) => (
              <Row
                key={i}
                label={a.departure_date || `Departure ${i + 1}`}
                value={
                  <>
                    {a.sectors.filter((x) => x.origin).map((x) => `${x.origin}→${x.destination}${x.flight_number ? ` ${x.flight_number}` : ""}`).join(", ") || "—"}
                    <span className="text-gray-400 font-normal"> · {num(a.requested_pax) ?? 0} seats</span>
                  </>
                }
              />
            ))}
          </div>
        )}
      </section>

      <section>
        <p className="text-[11px] font-bold text-gray-700 uppercase tracking-wide mb-2">Fare</p>
        {priced.length === 0 ? (
          <p className="text-[11px] text-amber-600">Not priced yet — deposits and penalties cannot be worked out.</p>
        ) : (
          <>
            <div className="space-y-1">
              {priced.map((f, i) => (
                <Row key={i} label={f.label || COMPONENT_LABEL[f.component_code]}
                  value={<span className="tabular-nums">{inr(num(f.amount_per_pax))}</span>} />
              ))}
            </div>
            <div className="mt-2 pt-2 border-t border-gray-100 space-y-1">
              <Row label="Per passenger" value={<span className="tabular-nums">{inr(perPax)}</span>} />
              <Row label={`× ${seats} seats`} value={<span className="tabular-nums font-semibold">{inr(perPax * seats)}</span>} />
            </div>
          </>
        )}
      </section>

      <section>
        <p className="text-[11px] font-bold text-gray-700 uppercase tracking-wide mb-2">
          Payment ({instalments.length})
        </p>
        {instalments.length === 0 ? (
          <p className="text-[11px] text-gray-400">No instalments yet.</p>
        ) : (
          <div className="space-y-1">
            {instalments.map((x, i) => {
              const explicit = num(x.amount);
              const computed = explicit ?? ((basisTotals[x.pct_basis] ?? 0) * (num(x.pct) ?? 0)) / 100;
              return (
                <Row
                  key={i}
                  label={`${PAYMENT_KIND_LABEL[x.kind]}${x.due_date ? ` · ${x.due_date}` : ""}`}
                  value={
                    <>
                      <span className="tabular-nums">{inr(computed)}</span>
                      {num(x.pct) != null && (
                        <span className="text-gray-400 font-normal"> ({x.pct}% of {FARE_BASIS_LABEL[x.pct_basis]})</span>
                      )}
                      {x.refundable === "no" && <span className="text-red-500 font-normal"> · forfeited on cancellation</span>}
                    </>
                  }
                />
              );
            })}
          </div>
        )}
      </section>

      <section>
        <p className="text-[11px] font-bold text-gray-700 uppercase tracking-wide mb-2">
          Deadlines ({deadlines.length}) · Terms ({terms.length})
        </p>
        <div className="space-y-1">
          {deadlines.map((d, i) => (
            <Row key={`d${i}`} label={DEADLINE_TYPE_LABEL[d.deadline_type] ?? d.deadline_type}
              value={d.stated_date || (d.offset_hours ? `${d.offset_hours}h before departure` : d.offset_days ? `${d.offset_days} days before departure` : "—")} />
          ))}
          {Object.entries(byRule).map(([rule, n]) => (
            <Row key={rule} label={TERM_RULE_LABEL[rule] ?? rule} value={`${n} rule${n !== 1 ? "s" : ""}`} />
          ))}
          {terms.length === 0 && (
            <p className="text-[11px] text-amber-600">
              No cancellation terms — the contract&apos;s cost-to-cancel cannot be shown.
            </p>
          )}
        </div>
      </section>

      {(pnr || passengers > 0) && (
        <section>
          <p className="text-[11px] font-bold text-gray-700 uppercase tracking-wide mb-2">Passengers</p>
          <Row label={pnr || "No PNR"} value={`${passengers} name${passengers !== 1 ? "s" : ""}`} />
        </section>
      )}

      <p className="text-[10px] text-gray-400 border-t border-gray-100 pt-2">
        Deadlines are generated from the instalment dates, the departures, and the
        cancellation bands once the contract is created — including a reminder on the last
        day before each cancellation charge goes up.
      </p>
    </div>
  );
}
