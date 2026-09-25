/**
 * Series / SIT / MICE / Group contracts — shared types and presentation helpers.
 *
 * Mirrors `backend/app/schemas/series.py`. Anything the server derives on read
 * (urgency, overdue, outstanding) arrives on the payload and is NOT recomputed here:
 * the browser's clock is not the one the contract is judged by, and two sources of
 * "is this late" disagree the moment a laptop's timezone is wrong.
 */

export const CONTRACT_TYPES = ["SERIES", "SIT", "MICE", "GROUP"] as const;
export type ContractType = (typeof CONTRACT_TYPES)[number];

export const CONTRACT_TYPE_LABEL: Record<string, string> = {
  SERIES: "Series",
  SIT: "SIT",
  MICE: "MICE",
  GROUP: "Group",
};

/** What each kind actually means commercially — shown as help text on the wizard. */
export const CONTRACT_TYPE_HINT: Record<string, string> = {
  SERIES: "Repeated space across a season — one row per departure.",
  SIT: "A single special-interest movement.",
  MICE: "A meeting, incentive, conference or event movement.",
  GROUP: "A one-off block for a single departure.",
};

export const SOURCE_TYPES = ["AIRLINE", "B2B"] as const;
export const CONTRACT_STATUSES = [
  "draft", "pending_review", "active", "closed", "cancelled",
] as const;

export const CABINS = ["ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST"] as const;
export const CABIN_LABEL: Record<string, string> = {
  ECONOMY: "Economy",
  PREMIUM_ECONOMY: "Premium Economy",
  BUSINESS: "Business",
  FIRST: "First",
};

export const PAX_TYPES = ["ADT", "CHD", "INF_SEAT", "INF_LAP"] as const;
export const PAX_TYPE_LABEL: Record<string, string> = {
  ADT: "Adult",
  CHD: "Child",
  INF_SEAT: "Infant (seat)",
  INF_LAP: "Infant (lap)",
};

/**
 * Fare components. The order here is the order a contract prints them, and the codes
 * match `uploaded_tickets` (sell_fare / sell_tax_yq / sale_yr / sell_tax) so contracted
 * and actual can be compared line by line.
 */
export const COMPONENT_CODES = [
  "BASE", "YQ", "YR_I", "YR_F", "TAX_STATUTORY", "OT", "FEE",
] as const;
export const COMPONENT_LABEL: Record<string, string> = {
  BASE: "Net fare (base)",
  YQ: "Carrier surcharge (YQ)",
  YR_I: "Carrier surcharge (YR-I)",
  YR_F: "Sustainable fuel (YR-F)",
  TAX_STATUTORY: "Statutory taxes",
  OT: "Other charges",
  FEE: "Fees",
};

/**
 * What a percentage is a percentage OF.
 *
 * The two reference contracts do not agree: Air India quotes penalties against
 * "AI retention (Base + YQ)", Air France against the net fare alone. A percentage
 * without one of these is not a number the server can price.
 */
export const FARE_BASES = [
  "NET_FARE", "AI_RETENTION", "FARE_PLUS_SURCHARGES", "TOTAL", "TAX_ONLY",
] as const;
export const FARE_BASIS_LABEL: Record<string, string> = {
  NET_FARE: "Net fare",
  AI_RETENTION: "Airline retention (base + YQ)",
  FARE_PLUS_SURCHARGES: "Fare + surcharges",
  TOTAL: "Total incl. taxes",
  TAX_ONLY: "Statutory taxes only",
};

export const PAYMENT_KINDS = [
  "ADVANCE_DEPOSIT", "DEPOSIT", "BALANCE", "FINAL_PAYMENT",
] as const;
export const PAYMENT_KIND_LABEL: Record<string, string> = {
  ADVANCE_DEPOSIT: "Advance deposit",
  DEPOSIT: "Deposit",
  BALANCE: "Balance",
  FINAL_PAYMENT: "Final payment",
};

export const DEADLINE_TYPES = [
  "ADVANCE_DEPOSIT", "DEPOSIT", "NAME_LIST", "SEAT_RELEASE", "FINAL_PAYMENT",
  "TICKETING", "NO_SHOW_CUTOFF", "DEVIATION_CUTOFF", "DEPARTURE",
  "OPTION_EXPIRY", "PENALTY_STEP",
] as const;
/** Deadlines a person enters; the rest are generated from payments, departures and terms. */
export const MANUAL_DEADLINE_TYPES = [
  "NAME_LIST", "TICKETING", "SEAT_RELEASE", "NO_SHOW_CUTOFF", "DEVIATION_CUTOFF",
] as const;
export const DEADLINE_TYPE_LABEL: Record<string, string> = {
  ADVANCE_DEPOSIT: "Advance deposit",
  DEPOSIT: "Deposit",
  NAME_LIST: "Name list",
  SEAT_RELEASE: "Seat release",
  FINAL_PAYMENT: "Final payment",
  TICKETING: "Ticketing",
  NO_SHOW_CUTOFF: "No-show cut-off",
  DEVIATION_CUTOFF: "Deviation cut-off",
  DEPARTURE: "Departure",
  OPTION_EXPIRY: "Offer expiry",
  PENALTY_STEP: "Cancellation charge rises",
};

// ── Terms: what a change or a cancellation costs ────────────────────────────

export const TERM_RULE_TYPES = [
  "CANCELLATION", "SEAT_RELEASE", "NAME_CHANGE", "DEVIATION", "REISSUE",
  "NO_SHOW", "REFUND", "MATERIALIZATION",
] as const;
export const TERM_RULE_LABEL: Record<string, string> = {
  CANCELLATION: "Cancellation",
  SEAT_RELEASE: "Seat release",
  NAME_CHANGE: "Name change",
  DEVIATION: "Deviation",
  REISSUE: "Reissue",
  NO_SHOW: "No-show",
  REFUND: "Refund",
  MATERIALIZATION: "Below materialisation",
};
export const TERM_SCOPES = ["GROUP", "PARTIAL", "PER_PAX"] as const;
export const TERM_SCOPE_LABEL: Record<string, string> = {
  GROUP: "Whole group",
  PARTIAL: "Part of group",
  PER_PAX: "Per passenger",
};
export const TERM_PHASES = [
  "ANY", "BEFORE_DEPOSIT", "AFTER_DEPOSIT_BEFORE_FINAL", "AFTER_FINAL_PAYMENT",
  "BEFORE_TICKETING", "AFTER_TICKETING",
] as const;
export const TERM_PHASE_LABEL: Record<string, string> = {
  ANY: "Any time",
  BEFORE_DEPOSIT: "Before deposit",
  AFTER_DEPOSIT_BEFORE_FINAL: "Deposit → final payment",
  AFTER_FINAL_PAYMENT: "After final payment",
  BEFORE_TICKETING: "Before ticketing",
  AFTER_TICKETING: "After ticketing",
};
export const TERM_CHARGE_TYPES = [
  "FREE", "PCT_OF_BASIS", "FIXED_PER_PAX", "FIXED_TOTAL", "DEPOSIT_FORFEIT",
  "NON_REFUNDABLE", "TAXES_ONLY_REFUNDABLE", "FARE_DIFFERENCE", "NOT_PERMITTED",
] as const;
export const TERM_CHARGE_LABEL: Record<string, string> = {
  FREE: "Free",
  PCT_OF_BASIS: "% of",
  FIXED_PER_PAX: "Fixed per pax",
  FIXED_TOTAL: "Fixed total",
  DEPOSIT_FORFEIT: "Deposit forfeited",
  NON_REFUNDABLE: "Non-refundable",
  TAXES_ONLY_REFUNDABLE: "Only taxes refunded",
  FARE_DIFFERENCE: "Fare difference",
  NOT_PERMITTED: "Not permitted",
};
export const DOCUMENT_KIND_LABEL: Record<string, string> = {
  QUOTATION: "Quotation",
  CONTRACT: "Contract",
  AMENDMENT: "Amendment",
  NAME_LIST: "Name list",
  OTHER: "Other",
};

export const DEADLINE_ANCHORS = ["DEPARTURE", "CONTRACT_DATE", "ADVANCE_DEPOSIT"] as const;
export const ANCHOR_LABEL: Record<string, string> = {
  DEPARTURE: "before departure",
  CONTRACT_DATE: "after the contract date",
  ADVANCE_DEPOSIT: "after the advance deposit",
};

// ── Payload types ────────────────────────────────────────────────────────────

export type Sector = {
  id?: number;
  allocation_id?: number;
  segment_no?: number | null;
  direction?: string | null;
  origin?: string | null;
  destination?: string | null;
  airline_code?: string | null;
  flight_number?: string | null;
  departure_at?: string | null;
  arrival_at?: string | null;
  cabin?: string | null;
  rbd?: string | null;
  allocated_pax?: number | null;
};

export type Passenger = {
  id?: number;
  booking_id?: number;
  allocation_id?: number;
  title?: string | null;
  first_name?: string | null;
  middle_name?: string | null;
  last_name?: string | null;
  pax_type?: string | null;
  occupies_seat?: boolean;
  counts_for_materialization?: boolean;
  date_of_birth?: string | null;
  gender?: string | null;
  nationality?: string | null;
  passport_number?: string | null;
  passport_expiry?: string | null;
  name_status?: string | null;
  ticket_number?: string | null;
  ticket_status?: string | null;
};

export type Booking = {
  id: number;
  allocation_id: number;
  pnr: string;
  airline_pnr?: string | null;
  tour_code?: string | null;
  booking_status?: string | null;
  seats?: number | null;
  tickets_issued: number;
  ticket_numbers?: string[] | null;
  amount_issued: number;
  last_matched_at?: string | null;
  passengers: Passenger[];
};

export type Allocation = {
  id: number;
  contract_id: number;
  allocation_ref?: string | null;
  departure_date?: string | null;
  status?: string | null;
  requested_pax?: number | null;
  /** Set when the advance deposit is paid — the denominator the 80% floor uses. */
  firmed_pax?: number | null;
  minimum_pax?: number | null;
  maximum_pax?: number | null;
  booked_pax: number;
  named_pax: number;
  ticketed_pax: number;
  released_pax: number;
  cancelled_pax: number;
  materialization_pct?: number | null;
  amount_issued: number;
  sectors: Sector[];
  bookings: Booking[];
};

export type FareComponent = {
  id?: number;
  contract_id?: number;
  allocation_id?: number | null;
  component_code?: string | null;
  label?: string | null;
  amount_per_pax?: number | null;
  is_guaranteed_until_ticketing?: boolean | null;
  is_refundable_on_noshow?: boolean | null;
  sort_order?: number | null;
};

export type FareSummary = {
  per_pax: number;
  total: number;
  seats: number;
  guaranteed_per_pax: number;
  exposed_per_pax: number;
  refundable_on_noshow_per_pax: number;
  by_component: Record<string, number>;
  bases: Record<string, number>;
};

export type Payment = {
  id: number;
  schedule_id: number;
  amount?: number | null;
  paid_on?: string | null;
  method?: string | null;
  reference?: string | null;
  notes?: string | null;
  created_at?: string | null;
};

export type ScheduleRow = {
  id: number;
  contract_id: number;
  allocation_id?: number | null;
  kind?: string | null;
  seq: number;
  due_date?: string | null;
  amount?: number | null;
  pct?: number | null;
  pct_basis?: string | null;
  status?: string | null;
  paid_amount: number;
  paid_on?: string | null;
  notes?: string | null;
  is_refundable?: boolean | null;
  due_offset_days?: number | null;
  payments: Payment[];
  // Derived server-side against today's date.
  outstanding: number;
  is_overdue: boolean;
  days_remaining?: number | null;
};

export type Deadline = {
  id: number;
  contract_id: number;
  allocation_id?: number | null;
  deadline_type?: string | null;
  anchor?: string | null;
  offset_days?: number | null;
  offset_hours?: number | null;
  computed_date?: string | null;
  stated_date?: string | null;
  effective_date?: string | null;
  /** The contract's own date disagreed with the offset it also printed. */
  has_divergence: boolean;
  status?: string | null;
  met_on?: string | null;
  action_required?: string | null;
  urgency?: string | null;
  days_remaining?: number | null;
};

export type Contract = {
  id: number;
  contract_type?: string | null;
  contract_number?: string | null;
  group_reference?: string | null;
  group_name?: string | null;
  source_type?: string | null;
  agent_name?: string | null;
  airline_code?: string | null;
  airline_name?: string | null;
  currency: string;
  contracted_pax?: number | null;
  minimum_pax?: number | null;
  cabin?: string | null;
  contract_date?: string | null;
  travel_from?: string | null;
  travel_to?: string | null;
  status?: string | null;
  notes?: string | null;
  option_expires_on?: string | null;
  supplier_ref?: string | null;
  materialization_floor_pct?: number | null;
  foc_per_paid?: number | null;
  baggage_allowance?: string | null;
  event_name?: string | null;

  allocations_count: number;
  seats_allocated: number;
  seats_ticketed: number;
  contract_cost: number;
  amount_issued: number;
  penalty_amount: number;
  /** sell − cost − penalties. Positive means the contract earned money. */
  margin: number;
  match_status?: string | null;
  last_matched_at?: string | null;
  created_at?: string | null;

  next_deadline?: Deadline | null;
  amount_due: number;
  overdue_count: number;
};

export type Term = {
  id?: number;
  contract_id?: number;
  allocation_id?: number | null;
  rule_type: string;
  scope?: string | null;
  phase?: string | null;
  days_before_max?: number | null;
  days_before_min?: number | null;
  share_min_pct?: number | null;
  share_max_pct?: number | null;
  charge_type: string;
  charge_value?: number | null;
  charge_basis?: string | null;
  cabin?: string | null;
  plus_gst?: boolean | null;
  description?: string | null;
  source_text?: string | null;
  source_page?: number | null;
  /** Plain-English line built by the server. */
  summary?: string | null;
};

/** What cancelling one whole departure would cost today — and until when. */
export type Exposure = {
  allocation_id: number;
  departure_date?: string | null;
  days_before?: number | null;
  description?: string | null;
  per_pax?: number | null;
  seats: number;
  amount?: number | null;
  plus_gst: boolean;
  holds_until?: string | null;
  next_description?: string | null;
  next_per_pax?: number | null;
};

export type SeriesDocument = {
  id: number;
  contract_id?: number | null;
  doc_kind: string;
  file_name: string;
  file_size?: number | null;
  page_count?: number | null;
  scanned_pages?: number | null;
  extraction_status: "stored" | "processing" | "done" | "failed" | "skipped";
  extraction_error?: string | null;
  extraction_model?: string | null;
  extraction_ms?: number | null;
  extracted_at?: string | null;
  created_at?: string | null;
  stored_remotely: boolean;
};

export type ContractDetail = Contract & {
  allocations: Allocation[];
  fare_components: FareComponent[];
  payment_schedule: ScheduleRow[];
  deadlines: Deadline[];
  fare_summary: FareSummary;
  terms: Term[];
  documents: SeriesDocument[];
  exposure: Exposure[];
};

// ── AI reading of an uploaded contract ──────────────────────────────────────

export type DraftWarning = { level: "error" | "warning" | "info"; field?: string | null; message: string };
export type Evidence = Record<string, { page?: number | null; quote?: string | null }>;

/** What the server read out of a PDF, shaped like the create payload. */
export type ExtractionDraft = {
  header: Record<string, string | number | null>;
  allocations: {
    departure_date?: string | null;
    requested_pax?: number | null;
    sectors: Partial<Sector>[];
  }[];
  fare_components: FareComponent[];
  payment_schedule: Partial<ScheduleRow>[];
  deadlines: Partial<Deadline>[];
  terms: Term[];
  passengers: Passenger[];
  evidence: Evidence;
  warnings: DraftWarning[];
  summary?: string | null;
  doc_kind?: string | null;
};

export type ExtractionResponse = {
  document: SeriesDocument;
  draft: ExtractionDraft | null;
  duplicate_of?: SeriesDocument | null;
};

export type MatchResult = {
  contracts: number;
  allocations: number;
  bookings: number;
  pending: number;
  partial: number;
  complete: number;
  over_issued: number;
  tickets_matched: number;
  amount_matched: number;
  margin_total: number;
};

export type ActionItem = {
  contract_id: number;
  contract_number?: string | null;
  group_name?: string | null;
  airline_code?: string | null;
  kind: string;
  label: string;
  due_date?: string | null;
  urgency: string;
  days_remaining?: number | null;
  amount?: number | null;
};

export type ActionCenter = {
  as_of: string;
  overdue: ActionItem[];
  today: ActionItem[];
  critical: ActionItem[];
  soon: ActionItem[];
  total_overdue_amount: number;
  below_materialization: ActionItem[];
};

// ── Presentation ─────────────────────────────────────────────────────────────

export const API_BASE = "/series-contracts";

export const inr = (v: number | null | undefined) =>
  v == null
    ? "—"
    : v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Compact money for tiles — 12.5L rather than 1,250,000.00. */
export const inrShort = (v: number | null | undefined) => {
  if (v == null) return "—";
  const abs = Math.abs(v);
  if (abs >= 1e7) return `${(v / 1e7).toFixed(2)} Cr`;
  if (abs >= 1e5) return `${(v / 1e5).toFixed(2)} L`;
  return inr(v);
};

export const MATCH_STATUS_STYLE: Record<string, string> = {
  pending: "bg-gray-50 text-gray-500 border-gray-200",
  partial: "bg-amber-50 text-amber-700 border-amber-200",
  complete: "bg-emerald-50 text-emerald-700 border-emerald-200",
  over_issued: "bg-red-50 text-red-700 border-red-200",
};
export const MATCH_STATUS_LABEL: Record<string, string> = {
  pending: "Pending",
  partial: "Partial",
  complete: "Complete",
  over_issued: "Over-issued",
};

export const CONTRACT_STATUS_STYLE: Record<string, string> = {
  draft: "bg-gray-50 text-gray-500 border-gray-200",
  pending_review: "bg-amber-50 text-amber-700 border-amber-200",
  active: "bg-emerald-50 text-emerald-700 border-emerald-200",
  closed: "bg-slate-100 text-slate-600 border-slate-200",
  cancelled: "bg-red-50 text-red-600 border-red-200",
};
export const CONTRACT_STATUS_LABEL: Record<string, string> = {
  draft: "Draft",
  pending_review: "In review",
  active: "Active",
  closed: "Closed",
  cancelled: "Cancelled",
};

/** Urgency colours, shared by the deadline list, the money view and the action centre. */
export const URGENCY_STYLE: Record<string, string> = {
  overdue: "bg-red-50 text-red-700 border-red-200",
  today: "bg-orange-50 text-orange-700 border-orange-200",
  critical: "bg-amber-50 text-amber-700 border-amber-200",
  soon: "bg-blue-50 text-blue-700 border-blue-200",
  scheduled: "bg-gray-50 text-gray-500 border-gray-200",
  settled: "bg-emerald-50 text-emerald-700 border-emerald-200",
  undated: "bg-gray-50 text-gray-400 border-gray-200",
};

/** "in 6 days" / "4 days ago" / "today" — from the server's own day count. */
export function relativeDays(days: number | null | undefined): string {
  if (days == null) return "—";
  if (days === 0) return "today";
  if (days > 0) return `in ${days} day${days === 1 ? "" : "s"}`;
  const past = Math.abs(days);
  return `${past} day${past === 1 ? "" : "s"} ago`;
}

export const routeOf = (sectors: Sector[] | undefined): string => {
  if (!sectors?.length) return "—";
  const ordered = [...sectors].sort((a, b) => (a.segment_no ?? 0) - (b.segment_no ?? 0));
  const points: string[] = [];
  ordered.forEach((s) => {
    if (s.origin && points[points.length - 1] !== s.origin) points.push(s.origin);
    if (s.destination) points.push(s.destination);
  });
  return points.join(" → ") || "—";
};

/** The contract's own route, taken from its first departure. */
export const contractRoute = (allocations: Allocation[] | undefined): string =>
  allocations?.length ? routeOf(allocations[0].sectors) : "—";

export const materializationTone = (pct: number | null | undefined, floor = 80): string => {
  if (pct == null) return "text-gray-400";
  if (pct >= floor) return "text-emerald-600";
  if (pct >= floor - 10) return "text-amber-600";
  return "text-red-600";
};
