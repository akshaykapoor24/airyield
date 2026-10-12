"use client";

// Internal Statement → Create Ticket, laid out like the back-office "INT. Sales"
// screen agencies already punch into: one screen, ticket on the left, fare and
// commission on the right, sectors as a small table, and the rarely-used groups
// behind a tab strip. Nothing needs scrolling for a normal ticket.
//
// There is no statement row to fill in. WHO the ticket was sold to is picked on
// the ticket itself (Sold To → Customer / Corporate / Agency + the name from User
// master), and the ticket is filed into that party's manual-entry statement for
// the ticket's month — found if it exists, created if it does not. Arriving with
// ?statement=<batch_id> (a statement's "Add ticket" button, e.g. an uploaded one)
// files into that statement instead.
//
// The data path is the same as tickets/create/page.tsx — the debounced server
// preview is the single source of truth, legs are folded in by composeLegs, and
// saving hits the same two endpoints.

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import toast from "react-hot-toast";
import {
  AlertCircle, ChevronDown, ChevronLeft, CornerDownLeft, FilePlus, Layers, RefreshCw, RotateCcw, Save,
  Upload, X,
} from "lucide-react";
import api from "@/lib/api";
import { apiError } from "@/components/userMaster/shared";
import type { StatementOption } from "@/components/tickets/TicketFilingCard";
import { predictSegmentType } from "@/components/tickets/ItineraryLegsEditor";
import TaxBreakupEditor from "@/components/tickets/TaxBreakupEditor";
import AirlinePicker from "@/components/tickets/AirlinePicker";
import { agencyLabel, type AgencyRow } from "@/lib/counterparty";
import { corporateLabel, customerLabel, partyName, type Party } from "@/lib/party";
import {
  CUSTOMER_TYPE_LABEL, CUSTOMER_TYPE_MASTER, EMPTY_TAG, buildTagPayload, isTagComplete,
  type CustomerTag, type CustomerType,
} from "@/lib/customerType";
import {
  BLANK_LEG, LEG_SECTOR_RE, MANUAL_ENTRY_FILE_NAME, REQUIRED_KEYS,
  coerceFieldValue, composeLegs, fieldByKey, fieldsFor, groupedFieldsFor, inr, legFieldKeys,
  predictAdmAcmRa,
  type ItineraryLeg, type StatementType, type TicketField,
  type TicketExtractionPreview, type TicketRow,
} from "@/lib/ticketFields";

type Draft = Record<string, unknown>;
type Pax = { title: string; name: string; ticket: string };

// Courtesy titles as airlines print them after the name. The server strips them
// when it splits pax_name into last/first, so appending one is safe.
const PAX_TITLES = ["MR", "MRS", "MS", "MISS", "MSTR", "DR"];
const blankPax = (): Pax => ({ title: "MR", name: "", ticket: "" });

/** The statement list row, with the customer tag the server already returns. */
/** The fields Load original reads off a saved sale (GET /uploads/page). */
type OriginalTicket = Record<string, unknown> & {
  ticket_number?: string | null;
  invoice_type?: string | null;
  doc_no?: string | null;
  pax_name?: string | null;
  sector?: string | null;
  segments?: { origin?: string | null; destination?: string | null; class?: string | null;
               travel_date?: string | null; segment_type?: string | null }[] | null;
};

type FilingStatement = StatementOption & {
  customer_type?:      CustomerType | null;
  customer_agency_id?: number | null;
  corporate_id?:       number | null;
  customer_id?:        number | null;
  created_at?:         string;
};

const PREVIEW_DEBOUNCE_MS = 400;
const MAX_PAX = 50;
const isBlank = (v: unknown) => v === null || v === undefined || v === "";

// ── Sold To ──────────────────────────────────────────────────────────────────
// The desk's words for the three customer types. Stored on the row as `sold_to`;
// the customer tag that drives the commission run comes from the statement.

const SOLD_TO: { value: string; label: string; type: CustomerType }[] = [
  { value: "customer",  label: "Customer",  type: "direct" },
  { value: "corporate", label: "Corporate", type: "corporate" },
  { value: "agency",    label: "Agency",    type: "agency" },
];
const soldToFor = (t: CustomerType | null | undefined) =>
  SOLD_TO.find((s) => s.type === t)?.value ?? null;

// ── Layout ───────────────────────────────────────────────────────────────────
// Which catalog fields sit on the main screen. Everything else the statement type
// carries lands under "More details", so no field becomes unreachable.

const TICKET_KEYS = [
  // Laid out two per row, so order is position. Doc No. / Doc Date are the
  // statement's own DocNo and Doc Date (IS26/ 1067 for a sale, IR26/ 358 for a
  // refund) — the columns an uploaded statement fills, so both paths agree.
  "ticket_date", "gds_pnr", "doc_no", "doc_date", "invoice_type", "booking_ref", "air_pnr",
  "tour_code", "acc_code",
];
// Total Tax and Total Fare are shown, not saved; Invoice Amt is saved as total_amt —
// the column an uploaded statement's BillAmount lands in, and what every other
// reader of total_amt (billing included) already takes it to mean: the bill, net of
// discount and TDS.
const FARE_KEYS = [
  "sell_fare", "sell_tax_yq", "sale_yr", "sale_k3", "oc_tax", "other_tax",
  "sell_tax", "total_fare", "total_amt",
];
// THIS FORM PUNCHES A SALE. The one figure that matters is what the customer will
// be invoiced, so only the CLIENT side of the desk software's sheet feeds it: what
// is given to the client (Paid), and what is charged to them. The Received column
// and Supplier accounting are kept as RECORDS — saved, never added into the invoice.
//
// Discount (dis_sell, "Dis Sell") is a sell-side figure: the discount the customer
// gets, which their bill deducts — so it sits on the Paid side.
const COMM_GRID: { label: string; recd: string | null; paid: string | null }[] = [
  { label: "Commission", recd: "comm_sell",      paid: "comm_paid" },
  { label: "Incentive",  recd: "incentive_sell", paid: "incentive_paid" },
  { label: "PLB",        recd: "plb_recd",       paid: "plb_paid" },
  { label: "Discount",   recd: null,             paid: "dis_sell" },
];
// Recall (S) is the supplier's recall — a record, like the Received column.
const COMM_EXTRA_KEYS = ["comm_percent", "tds_sell", "disc_recall", "adm"];
// RAF is charged to the customer on a refund, so it is a client charge.
const CLIENT_CHARGE_KEYS = ["serv_charge", "serv_charge_2", "serv_charge_3", "raf"];
const SUPPLIER_CHARGE_KEYS = ["supp_serv_charge_1", "supp_serv_charge_2", "card_charge"];
// Typed charges that may or may not carry GST — the user says which, per ticket.
// Charge 1 and #1 come from User master, whose rate already states its GST.
const GST_OPTIONAL_KEYS = new Set(["serv_charge_2", "serv_charge_3", "raf", "supp_serv_charge_2", "card_charge"]);
// Untaxed until switched on. A statement's refund line prints a flat GST beside its
// RAF rather than 18% of it, so taxing RAF by default would misstate it.
const NO_GST_BY_DEFAULT = ["raf"];
const COMM_KEYS = [
  ...COMM_GRID.flatMap((r) => [r.recd, r.paid].filter((k): k is string => !!k)), ...COMM_EXTRA_KEYS,
  ...CLIENT_CHARGE_KEYS, ...SUPPLIER_CHARGE_KEYS, "supp_serv_gst",
];
// GST on our service charges as ONE figure, gst_sell — what the statement prints
// and what an uploaded statement's GST column lands in. The CGST + SGST / IGST split
// is shown beside it for the desk, not saved: billing decides heads when it invoices.
const GST_KEYS = ["gst_sell"];
const TAX_PART_KEYS = ["sell_tax_yq", "sale_yr", "sale_k3", "oc_tax", "other_tax"];

// ── Sale or refund ───────────────────────────────────────────────────────────
// A refund line on the statement prints the fare side NEGATIVE and the charges
// POSITIVE: −62,995 basic, −2,046 taxes, +415 RAF, +18 GST. The desk types every
// figure as printed but without signs, and Refund applies them — to these keys.
const REFUND_TYPES = new Set(["Credit Note", "Refund"]);
const NEGATE_ON_REFUND = [
  "sell_fare", ...TAX_PART_KEYS,
  "comm_sell", "comm_paid", "incentive_sell", "incentive_paid", "plb_recd", "plb_paid",
  "dis_sell", "tds_sell",
];

// ── Auto totals ──────────────────────────────────────────────────────────────
// ONE net: the Invoice Amount, what the customer will be billed — saved as
// total_amt, the column an uploaded statement's BillAmount lands in.
// What is given to the client comes off; TDS (which the client deducts and pays to
// the government on our behalf), recalls and charges go on. Comm. % is a rate, so
// it is never counted, and nothing on the supplier side is counted at all.
//
// Checked against a statement line:
//   55,062 fare − 205.81 Discount + 4.12 TDS + 100 Serv. Chrgs + 18 GST = 54,978.31
// printed as BillAmount 54,978.00 — rounded to the rupee, as the invoice therefore
// is too. A refund works out the same way on signed figures:
//   −55,062 + 205.81 − 4.12 + 26,581 RAF + 18 GST = −28,261.31 → −28,261.
const INVOICE_LESS = ["comm_paid", "incentive_paid", "plb_paid", "dis_sell"];
const INVOICE_PLUS = ["tds_sell", "disc_recall", ...CLIENT_CHARGE_KEYS, ...GST_KEYS];

type Totals = {
  /** Shown only — Basic plus the tax parts. */
  sell_tax: number | null; total_fare: number | null;
  /** The Invoice Amount, saved. */
  total_amt: number | null;
  /** What rounding the invoice to the rupee added or took off. */
  round_off: number | null;
};

const AUTO_NOTE: Record<string, string> = {
  sell_tax:   "YQ + YR + K3 + OC + Other Taxes. Shown only, not saved.",
  total_fare: "Basic + Total Tax. Shown only, not saved.",
  total_amt:  "What the customer is invoiced (the statement's BillAmount), rounded to the rupee: Total Fare − Commission/Incentive/PLB/Discount paid + TDS + Disc Recall + Serv. Chrgs 1–3 + RAF + GST. The Received column and Supplier accounting are records and are not included.",
};

// Display-only figures dressed as catalog fields, so they share CompactField's look.
const SHOWN_FIELDS: Record<string, TicketField> = {
  total_fare: { key: "total_fare", label: "Total Fare", type: "number", group: "fare" },
};

// ── Charges from User master ─────────────────────────────────────────────────
// The answer of POST /ticket-charges/quote (backend/app/api/v1/ticket_charges.py).

type FeeQuote = {
  source: string; fee_type: string; fee_value: number; gst_treatment: string;
  amount: number; taxable: number; gst: number; gross: number; note: string;
};
type ChargeQuote = {
  client: FeeQuote | null;
  supplier: FeeQuote | null;
  gst_rate: number;
  interstate: boolean | null;
  gst_note: string | null;
};

type MasterCharges = {
  /** What the master says each auto-filled field should hold. */
  values: Record<string, number | null>;
  /** Tooltip per field: where its figure came from. */
  notes: Record<string, string>;
  /** GST on all client charges, before the CGST/SGST/IGST split. */
  gstTotal: number | null;
  /** How the GST divides by place of supply — shown, not saved. */
  split: { cgst: number | null; sgst: number | null; igst: number | null };
};

/**
 * The fields User master fills, given the quote and what the user has typed.
 *
 * Client charge 1 is the master's TAXABLE value — for a GST-inclusive rate the tax
 * is backed out, so the charge and its GST are never counted twice. The GST then
 * covers every client charge: the master's own GST figure on charge 1 (it knows
 * inclusive from exclusive), and the standard rate on charges 2 and 3 or on a
 * charge 1 the user typed over. The supplier side mirrors it: their charge #1 is
 * the taxable value and their GST on charges #1, #2 and card charges sits in its
 * own field, so each column shows a charge and its tax apart. RAF carries no GST.
 */
function masterCharges(
  d: Draft, q: ChargeQuote | null, manual: Set<string>, noGst: Set<string>, refund = false,
): MasterCharges {
  const val = (k: string) => (typeof d[k] === "number" ? (d[k] as number) : null);
  // A typed charge switched to "No GST" still counts as a charge, just untaxed.
  const taxed = (k: string) => (noGst.has(k) ? 0 : (val(k) ?? 0));
  const typed = (...ks: string[]) => ks.some((k) => (val(k) ?? 0) !== 0);
  const rate = q?.gst_rate ?? 0.18;

  // A refund does not re-charge the service fee — the statement's refund lines
  // carry none — so the master's fee is only offered on a sale.
  const sc1Master = q?.client && !refund ? q.client.taxable : null;
  const sc1 = manual.has("serv_charge") ? val("serv_charge") : sc1Master;
  const gst1 = manual.has("serv_charge") ? (sc1 ?? 0) * rate : (q?.client?.gst ?? 0);
  const others = taxed("serv_charge_2") + taxed("serv_charge_3") + taxed("raf");
  const anyCharge = sc1 !== null || typed("serv_charge_2", "serv_charge_3", "raf");
  const gstTotal = anyCharge ? round2(gst1 + others * rate) : null;

  let cgst: number | null = null, sgst: number | null = null, igst: number | null = null;
  if (gstTotal !== null && q?.interstate != null) {
    if (q.interstate) igst = gstTotal;
    else { cgst = round2(gstTotal / 2); sgst = round2(gstTotal - cgst); }
  }

  const sup1Master = q?.supplier ? q.supplier.taxable : null;
  const sup1 = manual.has("supp_serv_charge_1") ? val("supp_serv_charge_1") : sup1Master;
  const supGst1 = manual.has("supp_serv_charge_1") ? (sup1 ?? 0) * rate : (q?.supplier?.gst ?? 0);
  const supOthers = taxed("supp_serv_charge_2") + taxed("card_charge");
  const supGst = sup1 !== null || typed("supp_serv_charge_2", "card_charge") ? round2(supGst1 + supOthers * rate) : null;

  const pct = `${round2(rate * 100)}%`;
  const gstNote = q?.gst_note ?? "Pick who it was sold to — their state decides CGST + SGST or IGST.";
  return {
    values: {
      serv_charge: sc1Master,
      supp_serv_charge_1: sup1Master,
      gst_sell: gstTotal,
      supp_serv_gst: supGst,
    },
    notes: {
      serv_charge: q?.client ? `${q.client.source}: ${q.client.note}` : "No service fee set in User master",
      supp_serv_charge_1: q?.supplier ? `${q.supplier.source}: ${q.supplier.note}` : "No service charge set in Agency Master",
      supp_serv_gst: `Supplier's GST ${pct} on Serv. Chrgs #1, #2 and Card Chrgs.`,
      gst_sell: `GST ${pct} on service charges. ${gstNote}`,
    },
    gstTotal,
    split: { cgst, sgst, igst },
  };
}

const round2 = (n: number) => Math.round(n * 100) / 100;

/**
 * The document serial of a ticket number as a consolidator prints it,
 * "607 5808583279" → "5808583279" — mirroring sector_split.split_ticket_no on the
 * server, which stores the 3-digit airline code apart. Anything else is returned as is.
 */
function ticketSerial(raw: string): string {
  const m = raw.trim().match(/^(\d{3})[\s-]+(\d{6,})$/);
  return m ? m[2] : raw.trim();
}

// Not a ticket column — a display-only figure dressed as a field so it can share
// CompactField's read-only look.
const TOTAL_FIELD: TicketField = { key: "side_total", label: "Chrgs + GST", type: "number", group: "ancillary" };

/** A column's charges plus its GST, or null when the column is empty. */
function sideTotal(d: Draft, keys: string[]): number | null {
  const vs = keys.map((k) => d[k]).filter((v): v is number => typeof v === "number");
  return vs.length ? round2(vs.reduce((a, b) => a + b, 0)) : null;
}

// No spinner arrows — fares are typed, never stepped.
const NO_SPIN = "[appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none";

function computeTotals(d: Draft): Totals {
  const val = (k: string) => (typeof d[k] === "number" ? (d[k] as number) : null);
  const sum = (keys: string[]) => {
    const vs = keys.map(val).filter((v): v is number => v !== null);
    return vs.length ? vs.reduce((a, b) => a + b, 0) : null;
  };
  const tax = sum(TAX_PART_KEYS);
  const basic = val("sell_fare");
  const total = basic === null && tax === null ? null : (basic ?? 0) + (tax ?? 0);
  const net = (lessKeys: string[], plusKeys: string[]) => {
    const less = sum(lessKeys);
    const plus = sum(plusKeys);
    return total === null && less === null && plus === null
      ? null : round2((total ?? 0) - (less ?? 0) + (plus ?? 0));
  };
  const exact = net(INVOICE_LESS, INVOICE_PLUS);
  const invoice = exact === null ? null : Math.round(exact);
  return {
    sell_tax:   tax === null ? null : round2(tax),
    total_fare: total === null ? null : round2(total),
    total_amt:  invoice,
    round_off:  exact === null || invoice === null ? null : round2(invoice - exact),
  };
}

// Rendered by hand (airline, sold-to, pax) or written from them: the server splits
// pax_name into last/first, and customer_name is the Sold To party.
const HANDLED_KEYS = new Set([
  "airlines_code", "airline_name", "ticket_number", "pax_name", "sold_to", "customer_name",
  // net_amt is not punched (the statement prints none); the GST heads are shown only.
  "net_amt", "cgst_sell", "sgst_sell", "igst_sell",
  "last_name", "first_name",
  ...TICKET_KEYS, ...FARE_KEYS, ...COMM_KEYS, ...GST_KEYS,
]);

// Terser labels, in the desk software's own words where it has them.
const LABELS: Record<string, string> = {
  ticket_date: "Ticket Date", gds_pnr: "PNR No.", booking_ref: "Booking Ref",
  doc_no: "Doc No.", doc_date: "Doc Date", invoice_type: "Invoice Type", tour_code: "Deal Code",
  acc_code: "Acc Code",
  sell_fare: "Basic", sell_tax_yq: "'YQ' Tax", sale_yr: "'YR' Tax", sale_k3: "'K3' Tax",
  oc_tax: "'OC' Tax", other_tax: "Other Taxes", sell_tax: "Total Tax", total_fare: "Total Fare",
  total_amt: "Invoice Amt",
  comm_percent: "Comm. %", tds_sell: "TDS", disc_recall: "Disc Recall", adm: "Recall (S)",
  serv_charge: "Serv. Chrgs 1", serv_charge_2: "Serv. Chrgs 2", serv_charge_3: "Serv. Chrgs 3",
  supp_serv_charge_1: "Serv. Chrgs #1", supp_serv_charge_2: "Serv. Chrgs #2",
  card_charge: "Card Chrgs", raf: "RAF", supp_serv_gst: "GST",
  cgst_sell: "CGST", sgst_sell: "SGST", igst_sell: "IGST", gst_sell: "GST",
};

const LEG_HEADERS: Record<string, string> = {
  sector: "Sector", flight_no: "Flight", booking_class: "Class",
  departure_datetime: "Dep. Date", segment_type: "Seg. Type",
};

const INPUT = "border rounded-md px-2 py-1 text-xs focus:outline-none focus:ring-1";
const inputCls = (bad?: boolean) =>
  `${INPUT} ${bad ? "border-red-300 bg-red-50 focus:ring-red-400" : "border-gray-200 bg-white focus:ring-blue-400"}`;

// ── Filing by month ──────────────────────────────────────────────────────────

const pad = (n: number) => String(n).padStart(2, "0");
const todayISO = () => {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};
/** First and last day of the month an ISO date falls in. */
function monthBounds(iso: string): { from: string; to: string; label: string } {
  const [y, m] = iso.split("-").map(Number);
  const last = new Date(y, m, 0).getDate();
  const label = new Date(y, m - 1, 1).toLocaleDateString("en-IN", { month: "short", year: "numeric" });
  return { from: `${y}-${pad(m)}-01`, to: `${y}-${pad(m)}-${pad(last)}`, label };
}

/** Same party, by the ids the statement carries. A walk-in matches walk-in. */
function sameParty(s: FilingStatement, t: CustomerTag): boolean {
  if (s.customer_type !== t.customerType) return false;
  if (t.customerType === "agency")    return s.customer_agency_id === t.agencyId;
  if (t.customerType === "corporate") return s.corporate_id === t.corporateId;
  return t.customerId != null
    ? s.customer_id === t.customerId
    : s.customer_id == null && s.agency === (t.partyName || "Walk-in");
}

/**
 * The punched-ticket statement this party already has for that month, if any.
 * Uploaded statements are left alone — appending a hand-punched ticket to a
 * supplier's file would make it disagree with the file it came from.
 */
function findMonthStatement(list: FilingStatement[], t: CustomerTag, day: string) {
  return list
    .filter((s) => s.file_name === MANUAL_ENTRY_FILE_NAME && sameParty(s, t)
      && s.valid_from <= day && day <= s.valid_to)
    .sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""))[0];
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function CompactTicketForm({
  apiBase = "/internal-tickets",
  listHref = "/internal-statement/statements",
  uploadHref = "/internal-statement/upload",
}: {
  apiBase?: string;
  listHref?: string;
  uploadHref?: string;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [statements, setStatements] = useState<FilingStatement[]>([]);
  // Sold To — survives "Save & New", like the airline desk keeps the client.
  const [tag, setTag] = useState<CustomerTag>(EMPTY_TAG);
  const masters = useMasters();

  // Ticket — cleared by "Save & New".
  const [draft, setDraft] = useState<Draft>({});
  const [legs, setLegs] = useState<ItineraryLeg[]>([BLANK_LEG]);
  // The Sector route, one airport code per box. The leg rows are made from it.
  const [route, setRoute] = useState<string[]>(EMPTY_ROUTE);
  const onRouteChange = (next: string[]) => {
    setRoute(next);
    setLegs((prev) => legsFromRoute(next, prev));
  };
  const [paxes, setPaxes] = useState<Pax[]>([blankPax()]);
  // The Pax Count box as typed — may be empty mid-edit; paxes.length is the truth.
  const [paxCountText, setPaxCountText] = useState("1");
  const [touched, setTouched] = useState(false);
  // Bumped on every clear, to remount editors that keep their own local state.
  const [formKey, setFormKey] = useState(0);
  const [moreTab, setMoreTab] = useState<string | null>(null);

  const [rows, setRows] = useState<TicketRow[]>([]);
  const [previewWarnings, setPreviewWarnings] = useState<string[]>([]);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const [saving, setSaving] = useState(false);
  const [punched, setPunched] = useState(0);

  const loadStatements = useCallback(
    () => api.get<FilingStatement[]>(`${apiBase}/statements`).then((r) => {
      setStatements(r.data);
      return r.data;
    }),
    [apiBase],
  );
  useEffect(() => { loadStatements().catch(() => {}); }, [loadStatements]);

  // ?statement=<batch_id> — file into that statement (an uploaded one, say).
  const presetBatch = searchParams.get("statement");
  const preset = presetBatch ? statements.find((s) => s.batch_id === presetBatch) : undefined;

  // A ticket appended to a statement inherits its type and its customer.
  const effectiveType: StatementType = preset?.statement_type ?? "B2B";

  const available = useMemo(
    () => new Set(fieldsFor(effectiveType).map((f) => f.key)),
    [effectiveType],
  );
  const legKeys = useMemo(() => legFieldKeys(effectiveType), [effectiveType]);

  const moreGroups = useMemo(() => {
    const legSet = new Set(legKeys);
    return groupedFieldsFor(effectiveType)
      .map(({ group, fields }) => ({
        group,
        fields: fields.filter((f) => !HANDLED_KEYS.has(f.key) && !legSet.has(f.key)),
      }))
      .filter(({ group, fields }) => fields.length > 0 || !!group.custom);
  }, [effectiveType, legKeys]);

  // ── Rows sent to the server: one per passenger ────────────────────────────
  const soldTo = preset ? soldToFor(preset.customer_type) : soldToFor(tag.customerType);
  const clientName = preset ? preset.agency : (tag.partyName || (tag.customerType === "direct" ? "Walk-in" : ""));

  // ── Charges from User master ──────────────────────────────────────────────
  // The service charges and the GST on them come from the rates agreed at
  // onboarding (Agency / Corporate / Employee Master), quoted by the server on the
  // ticket's Total Fare. Each stays editable: typing into one makes it manual, and
  // ↺ hands it back to the master.
  const fareTotal = useMemo(() => computeTotals(draft).total_fare, [draft]);

  // Sale or refund, read off the Invoice Type itself so the two can never disagree:
  // a Credit Note (what an uploaded statement's refund line becomes) or Refund is a
  // refund, anything else a sale.
  const refund = REFUND_TYPES.has(String(draft.invoice_type ?? ""));
  const quoteParty = preset
    ? {
        customer_type: preset.customer_type ?? null,
        agency_id: preset.customer_agency_id ?? null,
        corporate_id: preset.corporate_id ?? null,
        customer_id: preset.customer_id ?? null,
      }
    : {
        customer_type: tag.customerType,
        agency_id: tag.customerType === "agency" ? tag.agencyId : null,
        corporate_id: tag.customerType === "corporate" ? tag.corporateId : null,
        customer_id: tag.customerType === "direct" ? tag.customerId : null,
      };
  // Both sides come from the Sold To party: an agency carries its service fee AND
  // its service charge; a corporate or customer carries a markup.
  const quoteKey = JSON.stringify({ ...quoteParty, base: fareTotal ?? 0 });
  const [quote, setQuote] = useState<ChargeQuote | null>(null);
  useEffect(() => {
    const body = JSON.parse(quoteKey);
    if (!body.customer_type) { setQuote(null); return; }
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      api.post<ChargeQuote>("/ticket-charges/quote", body, { signal: ctrl.signal })
        .then((r) => setQuote(r.data))
        .catch(() => { if (!ctrl.signal.aborted) setQuote(null); });
    }, PREVIEW_DEBOUNCE_MS);
    return () => { clearTimeout(t); ctrl.abort(); };
  }, [quoteKey]);

  // Keys the user has typed over. Anything not in here follows the master.
  const [manual, setManual] = useState<Set<string>>(new Set());
  // Typed charges the user switched to "No GST". Everything else is taxed at the standard rate.
  const [noGst, setNoGst] = useState<Set<string>>(() => new Set(NO_GST_BY_DEFAULT));
  const toggleGst = (key: string) =>
    setNoGst((prev) => { const next = new Set(prev); if (next.has(key)) next.delete(key); else next.add(key); return next; });
  const charges = useMemo(
    () => masterCharges(draft, quote, manual, noGst, refund),
    [draft, quote, manual, noGst, refund],
  );

  // Typed values, with every charge the user has not overridden filled from the master.
  const effective = useMemo<Draft>(() => {
    const out: Draft = { ...draft };
    for (const [k, v] of Object.entries(charges.values)) {
      if (!manual.has(k)) out[k] = v;
    }
    return out;
  }, [draft, charges, manual]);

  // What is actually saved: on a refund the fare side goes negative, exactly as the
  // statement prints it; the charges (RAF, service charges, GST) stay positive.
  const signed = useMemo<Draft>(() => {
    if (!refund) return effective;
    const out: Draft = { ...effective };
    for (const k of NEGATE_ON_REFUND) {
      if (typeof out[k] === "number") out[k] = -Math.abs(out[k] as number);
    }
    return out;
  }, [effective, refund]);

  // Total Tax, Total Fare and the Invoice Amount are worked out, not typed.
  const auto = useMemo(() => computeTotals(signed), [signed]);

  const composed = useMemo<Draft>(
    // Saved exactly as an uploaded statement line saves: the invoice in total_amt,
    // GST as one figure, no net_amt and no sell_tax (the statement prints neither).
    () => ({
      ...signed,
      total_amt: auto.total_amt,
      ...composeLegs(legs, effectiveType),
    }),
    [signed, auto, legs, effectiveType],
  );
  const outRows = useMemo<Draft[]>(
    () => paxes.map((p) => ({
      ...composed,
      ticket_number: p.ticket.trim() || null,
      // "SURNAME/FIRSTNAME MR" — the shape statements print and the server parses.
      pax_name: p.name.trim() ? `${p.name.trim()} ${p.title}`.trim() : null,
      sold_to: soldTo,
      customer_name: clientName || null,
    })),
    [composed, paxes, soldTo, clientName],
  );

  const draftIsEmpty = useMemo(
    () => paxes.every((p) => !p.name.trim() && !p.ticket.trim())
      && Object.values(composed).every(
        (v) => isBlank(v) || (typeof v === "object" && v !== null && Object.keys(v).length === 0)),
    [composed, paxes],
  );

  // ── Preview ───────────────────────────────────────────────────────────────
  const requestPreview = useCallback(
    async (rows: Draft[], signal?: AbortSignal) => {
      const { data } = await api.post<TicketExtractionPreview>(
        `${apiBase}/manual/preview`,
        { rows, statement_type: effectiveType },
        { signal },
      );
      return data;
    },
    [apiBase, effectiveType],
  );

  useEffect(() => {
    if (draftIsEmpty) {
      setRows([]); setPreviewWarnings([]); setPreviewError(null);
      return;
    }
    const ctrl = new AbortController();
    const t = setTimeout(async () => {
      setPreviewing(true);
      try {
        const data = await requestPreview(outRows, ctrl.signal);
        setRows(data.rows);
        setPreviewWarnings(data.warnings);
        setPreviewError(null);
      } catch {
        if (ctrl.signal.aborted) return;
        setPreviewError("Couldn't refresh the preview — check your connection.");
      } finally {
        if (!ctrl.signal.aborted) setPreviewing(false);
      }
    }, PREVIEW_DEBOUNCE_MS);
    return () => { clearTimeout(t); ctrl.abort(); };
  }, [outRows, draftIsEmpty, requestPreview]);

  const setField = (key: string, value: unknown) => {
    // Typing over a master-filled charge takes it out of the master's hands.
    if (key in charges.values) setManual((prev) => (prev.has(key) ? prev : new Set(prev).add(key)));
    setDraft((prev) => {
      const next = { ...prev };
      if (isBlank(value)) delete next[key]; else next[key] = value;
      return next;
    });
  };
  // ↺ — back to the master's figure.
  const resetToMaster = (key: string) => {
    setManual((prev) => { const next = new Set(prev); next.delete(key); return next; });
    setDraft((prev) => { const next = { ...prev }; delete next[key]; return next; });
  };

  const setPaxCount = (n: number) => {
    const count = Math.max(1, Math.min(MAX_PAX, Number.isFinite(n) ? Math.floor(n) : 1));
    setPaxes((prev) => count <= prev.length
      ? prev.slice(0, count)
      : [...prev, ...Array.from({ length: count - prev.length }, blankPax)]);
  };
  const setPax = (i: number, patch: Partial<Pax>) =>
    setPaxes((prev) => prev.map((p, j) => (j === i ? { ...p, ...patch } : p)));

  // ── Filing ────────────────────────────────────────────────────────────────
  const ticketDay = (draft.ticket_date as string) || todayISO();
  const month = monthBounds(ticketDay);
  const newStatementName = clientName && tag.customerType
    ? `${CUSTOMER_TYPE_LABEL[tag.customerType]} - ${clientName} - ${month.label}`
    : "";

  // ── Validation ────────────────────────────────────────────────────────────
  const punchedLegs = legs.filter((l) => (l.sector ?? "").trim() !== "");
  const legMalformed = punchedLegs.some(
    (l) => !LEG_SECTOR_RE.test((l.sector ?? "").trim().toUpperCase()),
  );
  const ticketMissing = paxes.map((p) => !p.ticket.trim());
  const missingRequired = REQUIRED_KEYS.filter((k) =>
    k === "ticket_number" ? ticketMissing.some(Boolean) : isBlank(composed[k]));
  const soldToReady = !!preset || isTagComplete(tag);
  const ticketReady = missingRequired.length === 0 && !legMalformed && rows.length > 0;

  const legSet = new Set(legKeys);
  const invalidKeys = new Set(touched ? missingRequired.filter((k) => !legSet.has(k)) : []);

  // Classified on the SERIAL, as the server does once it splits "607 5808583279" into
  // its airline code and serial — on the whole string, "607…" would read as an ADM.
  const predicted = predictAdmAcmRa(ticketSerial(paxes[0].ticket));
  const derived = rows[0];

  const focusFirst = () =>
    requestAnimationFrame(() => document.getElementById("ct-airlines_code")?.focus());

  // ── Refund: start from the ticket being refunded ──────────────────────────
  // A refund repeats the sale's fare and taxes with the signs turned, so the desk
  // types the ticket number and pulls the rest from the sale already on file
  // (uploaded or punched — both land in the same table). Amounts come in unsigned;
  // Refund mode signs them. RAF and charges are the refund's own, so stay blank.
  const [loadingOriginal, setLoadingOriginal] = useState(false);
  const loadOriginal = async () => {
    const serial = ticketSerial(paxes[0].ticket);
    if (!serial) { toast.error("Type the ticket number in Pax 1 first."); return; }
    setLoadingOriginal(true);
    try {
      const { data } = await api.get<{ rows: OriginalTicket[] }>(`${apiBase}/uploads/page`, {
        params: { search: serial, limit: 50 },
      });
      const sale = data.rows.find((r) =>
        String(r.ticket_number ?? "") === serial && !REFUND_TYPES.has(String(r.invoice_type ?? "")));
      if (!sale) { toast.error(`No sale of ticket ${serial} found in Internal Statement.`); return; }

      const abs = (v: unknown) => (typeof v === "number" ? Math.abs(v) : undefined);
      setDraft((prev) => {
        const next: Draft = { ...prev, invoice_type: prev.invoice_type ?? "Credit Note" };
        for (const k of ["airlines_code", "airline_name", "gds_pnr", "booking_ref", "tour_code", "acc_code", "ticket_date"]) {
          const v = sale[k as keyof OriginalTicket];
          if (v != null && v !== "") next[k] = v;
        }
        for (const k of [...NEGATE_ON_REFUND, "comm_percent"]) {
          const v = abs(sale[k as keyof OriginalTicket]);
          if (v !== undefined && v !== 0) next[k] = v;
        }
        return next;
      });
      if (sale.pax_name) {
        // "MR. SAHOTA/VIKAS" or "SAHOTA/VIKAS MR" → the title box and the name.
        const raw = sale.pax_name.trim().toUpperCase();
        const t = PAX_TITLES.find((x) => raw.startsWith(`${x}.`) || raw.startsWith(`${x} `) || raw.endsWith(` ${x}`));
        const name = t ? raw.replace(new RegExp(`^${t}\\.?\\s+|\\s+${t}$`), "").trim() : raw;
        setPax(0, { name, ...(t ? { title: t } : {}) });
      }
      // The route: from the legs saved inside the row, else from its sector string.
      const segs = Array.isArray(sale.segments) ? sale.segments : [];
      const codes = segs.length
        ? [segs[0].origin, ...segs.map((s) => s.destination)]
        : (sale.sector ?? "").toUpperCase().split(/[\s/]+/).filter((c, i, a) => c && c !== a[i - 1]);
      const clean = codes.filter((c): c is string => typeof c === "string" && /^[A-Z]{3}$/.test(c)).slice(0, MAX_ROUTE_POINTS);
      if (clean.length >= 2) {
        const nextRoute = [...clean, ...Array(MAX_ROUTE_POINTS - clean.length).fill("")];
        setRoute(nextRoute);
        setLegs(legsFromRoute(nextRoute, segs.map((s) => ({
          booking_class: s.class ?? null, departure_datetime: s.travel_date ?? null,
          segment_type: s.segment_type ?? null,
        }))));
      }
      toast.success(`Loaded ${sale.doc_no ? sale.doc_no.replace(/\s+/g, " ") : `ticket ${serial}`} — now add the RAF and charges.`);
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setLoadingOriginal(false);
    }
  };

  const clearTicket = () => {
    setDraft({}); setLegs([BLANK_LEG]); setRoute(EMPTY_ROUTE); setPaxes([blankPax()]); setPaxCountText("1"); setTouched(false);
    setManual(new Set()); setNoGst(new Set(NO_GST_BY_DEFAULT));
    setRows([]); setPreviewWarnings([]); setPreviewError(null);
    setFormKey((k) => k + 1);
  };

  // ── Save ──────────────────────────────────────────────────────────────────
  const save = async (andNew: boolean) => {
    setTouched(true);
    if (!soldToReady || !ticketReady || saving) return;
    setSaving(true);
    try {
      // Re-derive immediately before saving, in case Save landed mid-debounce.
      const fresh = await requestPreview(outRows);
      const out: TicketRow[] = fresh.rows.map((r, i) => ({ ...r, row_order: i + 1 }));

      let where: string;
      if (preset) {
        await api.post(`${apiBase}/statements/${preset.batch_id}/tickets`, { rows: out });
        where = preset.statement_name || preset.agency;
      } else {
        // Re-read the list so a statement opened in another tab is reused, not
        // duplicated. The list is per user, so each user keeps their own month.
        const list = await loadStatements().catch(() => statements);
        const existing = findMonthStatement(list, tag, ticketDay);
        if (existing) {
          await api.post(`${apiBase}/statements/${existing.batch_id}/tickets`, { rows: out });
          where = existing.statement_name || existing.agency;
        } else {
          await api.post(`${apiBase}/upload/confirm`, {
            file_name: MANUAL_ENTRY_FILE_NAME,
            rows: out,
            statement_type: "B2B",
            agency: clientName || "—",
            ...buildTagPayload(tag),
            statement_name: newStatementName || null,
            valid_from: month.from,
            valid_to: month.to,
          });
          where = newStatementName || "a new statement";
        }
      }

      const n = paxes.length;
      // Naming the hidden monthly batch would only confuse; a preset statement is real.
      toast.success(preset
        ? `${n} ticket${n !== 1 ? "s" : ""} added to “${where}”`
        : `${n} ticket${n !== 1 ? "s" : ""} saved`);
      setPunched((p) => p + n);

      if (!andNew) {
        router.push(listHref);
        return;
      }
      await loadStatements().catch(() => {});
      clearTicket();
      setSaving(false);
      focusFirst();
    } catch (e) {
      toast.error(apiError(e));
      setSaving(false);
    }
  };

  // Ctrl+Enter → Save & New, Ctrl+S → Save. Kept off plain Enter, which would
  // file half-typed tickets the moment someone confirms a field.
  const saveRef = useRef(save);
  saveRef.current = save;
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      if (e.key === "Enter") { e.preventDefault(); saveRef.current(true); }
      else if (e.key === "s" || e.key === "S") { e.preventDefault(); saveRef.current(false); }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  useEffect(() => { focusFirst(); }, []);

  // ── Field rendering ───────────────────────────────────────────────────────
  // An input with no label of its own — for the Received / Paid grid, whose rows
  // and columns carry the labels. A field the statement type lacks shows blank.
  const renderBare = (key: string, aria: string) => {
    const f = fieldByKey[key];
    if (!f || !available.has(key)) {
      return <span key={key} className={`${INPUT} border-gray-100 bg-gray-50 text-gray-300 text-center`}>—</span>;
    }
    return (
      <input
        key={key}
        id={`ct-${key}`}
        aria-label={aria}
        type="number"
        step="any"
        value={(draft[key] as number | undefined) ?? ""}
        placeholder="0.00"
        onChange={(e) => setField(key, coerceFieldValue(f, e.target.value))}
        onWheel={(e) => (e.target as HTMLInputElement).blur()}
        title={f.hint}
        className={`w-full min-w-0 text-right tabular-nums ${NO_SPIN} ${inputCls()}`}
      />
    );
  };

  const renderField = (key: string) => {
    if (key in AUTO_NOTE) {
      const af = fieldByKey[key] ?? SHOWN_FIELDS[key];
      if (!af) return null;
      return (
        <CompactField
          key={key}
          field={af}
          label={LABELS[key]}
          value={auto[key as keyof Totals]}
          emphasis={key === "total_amt"}
          readOnly
          note={AUTO_NOTE[key]}
          onChange={() => {}}
        />
      );
    }
    if (!available.has(key)) return null;
    const f = fieldByKey[key];
    if (!f) return null;
    return (
      <CompactField
        key={key}
        field={f}
        label={LABELS[key]}
        value={effective[key] as string | number | null}
        required={!!f.mapRequired}
        invalid={invalidKeys.has(key)}
        onChange={(raw) => setField(key, coerceFieldValue(f, raw))}
        master={key in charges.values ? {
          note: charges.notes[key],
          manual: manual.has(key),
          onReset: () => resetToMaster(key),
        } : undefined}
        // Offered once there is an amount to tax — a blank charge has no GST question.
        gstToggle={GST_OPTIONAL_KEYS.has(key) && typeof draft[key] === "number" && draft[key] !== 0 ? {
          on: !noGst.has(key),
          onToggle: () => toggleGst(key),
        } : undefined}
      />
    );
  };

  const multiPax = paxes.length > 1;

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="space-y-3">
      {/* header */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          <Link href={listHref} className="p-1.5 rounded-lg border border-gray-200 hover:bg-gray-50 text-gray-500">
            <ChevronLeft className="w-4 h-4" />
          </Link>
          <div>
            <h1 className="text-lg font-bold text-gray-900 uppercase tracking-wide leading-tight">Create Ticket</h1>
            <p className="text-[11px] text-gray-500">
              Punch tickets one after another — each is listed under Statements → All tickets
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {presetBatch && (
            <span className="flex items-center gap-1.5 pl-2.5 pr-1 py-1 rounded-full bg-blue-50 border border-blue-200 text-[11px] text-blue-800">
              <Layers className="w-3 h-3" />
              Adding to <b className="max-w-[220px] truncate">{preset ? (preset.statement_name || preset.agency) : "…"}</b>
              <button
                type="button"
                title="Stop adding to this statement"
                onClick={() => router.replace("/internal-statement/create")}
                className="p-0.5 rounded-full hover:bg-blue-100"
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          )}
          {punched > 0 && (
            <span className="px-2.5 py-1 rounded-full bg-emerald-50 border border-emerald-200 text-[11px] font-semibold text-emerald-700">
              {punched} punched this session
            </span>
          )}
          <Link
            href={uploadHref}
            className="flex items-center gap-1.5 px-3 py-1.5 border border-gray-200 rounded-lg text-xs text-gray-600 hover:bg-gray-50"
          >
            <Upload className="w-3.5 h-3.5" /> Upload statement instead
          </Link>
        </div>
      </div>

      {/* main two-column body */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3 items-start">
        {/* LEFT: ticket + sectors */}
        <div className="space-y-3">
          <Panel title="Ticket" color="#1e3a5f">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-2">
              <div className="sm:col-span-2 flex items-start gap-2 min-w-0 relative z-20">
                <label htmlFor="ct-airlines_code" className={SIDE_LABEL + " pt-1.5"}>
                  Airline<span className="text-red-500">*</span>
                </label>
                <div className="flex-1 min-w-0">
                  <AirlinePicker
                    hideLabel
                    inputId="ct-airlines_code"
                    code={String(draft.airlines_code ?? "")}
                    name={String(draft.airline_name ?? "")}
                    required
                    invalid={invalidKeys.has("airlines_code")}
                    onCodeChange={(v) => setField("airlines_code", v)}
                    onPick={(a) => { setField("airlines_code", a.iata_code); setField("airline_name", a.name); }}
                  />
                </div>
              </div>

              <SoldToRow
                tag={tag}
                setTag={setTag}
                locked={preset ? { soldTo: soldTo, name: preset.agency } : null}
                invalid={touched && !soldToReady}
                masters={masters}
              />

              <div className="sm:col-span-2 flex items-center gap-2 min-w-0">
                <label htmlFor="ct-pax_count" className={SIDE_LABEL}>Pax Count</label>
                {/* Plain text, not type=number: the box may be emptied while typing a
                    new count, and the spinner arrows only got in the way. */}
                <input
                  id="ct-pax_count"
                  type="text"
                  inputMode="numeric"
                  value={paxCountText}
                  onChange={(e) => {
                    const digits = e.target.value.replace(/\D/g, "").slice(0, 2);
                    setPaxCountText(digits);
                    const n = parseInt(digits, 10);
                    if (n >= 1) setPaxCount(n);
                  }}
                  onBlur={() => {
                    const n = Math.max(1, Math.min(MAX_PAX, parseInt(paxCountText, 10) || 1));
                    setPaxCountText(String(n));
                    setPaxCount(n);
                  }}
                  onFocus={(e) => e.target.select()}
                  className={`w-14 text-center tabular-nums ${inputCls()}`}
                />
                {multiPax && <span className="text-[10px] text-gray-400">one ticket per pax</span>}
              </div>

              <PaxRows paxes={paxes} setPax={setPax} showErrors={touched} />

              {/* The route as the desk software takes it: five 3-letter airport
                  boxes, slashes fixed, destination shown at the end. Each pair of
                  airports becomes a leg row in Sectors below. */}
              <div className="sm:col-span-2 flex items-center gap-2 min-w-0">
                <label htmlFor="ct-route-0" className={SIDE_LABEL}>
                  Sector<span className="text-red-500">*</span>
                </label>
                <RouteInput
                  codes={route}
                  onChange={onRouteChange}
                  invalid={touched && punchedLegs.length === 0}
                />
                <span className="shrink-0 text-[10px] text-gray-400">
                  {punchedLegs.length > 0
                    ? `${punchedLegs.length} leg${punchedLegs.length > 1 ? "s" : ""}`
                    : route[0] ? "add the next airport" : ""}
                </span>
              </div>

              {TICKET_KEYS.map(renderField)}
            </div>
            {predicted && (
              <p className="mt-2 text-[10px] text-amber-700">
                Ticket number prefix → saved as <b>{predicted}</b>.
              </p>
            )}
          </Panel>

          {/* A multi-sector ticket is saved as ONE row here — the legs travel inside
              it — so there is no per-leg split to preview. */}
          <Panel title="Sectors" color="#4f46e5">
            <SectorTable legs={legs} legKeys={legKeys} onChange={setLegs} />
            {previewError && (
              <p className="mt-2 flex items-center gap-1.5 text-[11px] text-red-600">
                <AlertCircle className="w-3.5 h-3.5" /> {previewError}
              </p>
            )}
          </Panel>
        </div>

        {/* RIGHT: fare | commission, GST under both */}
        <Panel
          title={`${refund ? "Refund" : "Fare & Commission"}${multiPax ? " — per pax" : ""}`}
          color={refund ? "#b45309" : "#059669"}
          right={
            // Sale or refund. A refund is typed as printed but without signs;
            // the fare side is saved negative, the charges positive.
            <div className="flex rounded-md overflow-hidden border border-white/30 text-[10px] font-bold">
              {([["Sale", false], ["Refund", true]] as const).map(([label, isRefund]) => (
                <button
                  key={label}
                  type="button"
                  onClick={() => setField("invoice_type", isRefund ? "Credit Note" : null)}
                  className={`px-2.5 py-0.5 ${refund === isRefund ? "bg-white text-gray-800" : "text-white/80 hover:bg-white/10"}`}
                >
                  {label}
                </button>
              ))}
            </div>
          }
        >
          {refund && (
            <div className="mb-3 -mt-1 flex items-center gap-2 flex-wrap px-3 py-2 rounded-lg bg-amber-50 border border-amber-200 text-[11px] text-amber-900">
              <span>
                Refund — type figures as printed, without signs. Fare, taxes, discount and TDS are
                saved negative; RAF, charges and GST positive.
              </span>
              <button
                type="button"
                onClick={loadOriginal}
                disabled={loadingOriginal}
                title="Fill the fare, taxes, route and passenger from the sale of the ticket number in Pax 1"
                className="ml-auto shrink-0 flex items-center gap-1 px-2.5 py-1 rounded-md bg-white border border-amber-300 font-semibold text-amber-800 hover:bg-amber-100 disabled:opacity-50"
              >
                {loadingOriginal ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Layers className="w-3 h-3" />}
                Load original ticket
              </button>
            </div>
          )}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-5">
            <div className="space-y-2">
              <SubHead>Publish fare</SubHead>
              {FARE_KEYS.map(renderField)}
              {auto.round_off !== null && auto.round_off !== 0 && (
                <p className="text-[10px] text-gray-400 text-right -mt-1">
                  Invoice rounded to the rupee — round off {auto.round_off > 0 ? "+" : ""}{auto.round_off.toFixed(2)}
                </p>
              )}
            </div>

            <div className="mt-3 sm:mt-0">
              <SubHead>Commission</SubHead>
              {/* Received from the supplier (a record) | paid to the client (in the invoice). */}
              <div className="grid grid-cols-[96px_minmax(0,1fr)_minmax(0,1fr)] gap-x-2 gap-y-2 items-center mt-2">
                <span />
                <span
                  className="text-[10px] font-bold text-gray-400 uppercase tracking-wider text-center"
                  title="What the supplier gave you. Saved as a record — not part of the invoice."
                >
                  Received <span className="normal-case font-medium">(record)</span>
                </span>
                <span
                  className="text-[10px] font-bold text-gray-500 uppercase tracking-wider text-center"
                  title="What you give the customer. Deducted from the invoice."
                >
                  Paid
                </span>
                {COMM_GRID.map((r) => (
                  <Fragment key={r.label}>
                    <span className={SIDE_LABEL + " w-auto"}>{r.label}</span>
                    {r.recd ? renderBare(r.recd, `${r.label} received`) : <span />}
                    {r.paid ? renderBare(r.paid, `${r.label} paid`) : <span />}
                  </Fragment>
                ))}
              </div>
              <div className="space-y-2 mt-2">
                {COMM_EXTRA_KEYS.map(renderField)}
              </div>
            </div>
          </div>

          {/* Service charges, split the way the desk software splits them — each
              side with its charges, then the GST on them, then the two together. */}
          <div className="mt-3 pt-3 border-t border-gray-100 grid grid-cols-1 sm:grid-cols-2 gap-x-5">
            <div className="space-y-2">
              <SubHead>Client accounting</SubHead>
              {CLIENT_CHARGE_KEYS.map(renderField)}
              {GST_KEYS.map(renderField)}
              {/* How that GST divides — shown for the desk, not saved. The split needs
                  both states, so say why it is missing rather than guess. */}
              {typeof effective.gst_sell === "number" && effective.gst_sell !== 0 && (
                quote?.interstate == null ? (
                  <p className="flex items-start gap-1.5 text-[10px] text-amber-700 pl-[104px] -mt-1">
                    <AlertCircle className="w-3 h-3 shrink-0 mt-px" />
                    Not split into CGST/SGST/IGST — {quote?.gst_note ?? "pick who it was sold to; their state decides."}
                  </p>
                ) : (
                  <p className="text-[10px] text-gray-400 pl-[104px] -mt-1" title={quote?.gst_note ?? undefined}>
                    {quote.interstate
                      ? <>IGST {inr(effective.gst_sell as number)}</>
                      : <>CGST {inr(round2((effective.gst_sell as number) / 2))} + SGST {inr(round2((effective.gst_sell as number) - round2((effective.gst_sell as number) / 2)))}</>}
                  </p>
                )
              )}
              <CompactField
                field={TOTAL_FIELD}
                label="Chrgs + GST"
                value={sideTotal(effective, [...CLIENT_CHARGE_KEYS, ...GST_KEYS])}
                readOnly
                note="Client service charges plus our GST on them. Shown only, not saved."
                onChange={() => {}}
              />
            </div>
            <div className="space-y-2 mt-3 sm:mt-0">
              <SubHead>Supplier accounting <span className="normal-case font-medium text-gray-400">(record)</span></SubHead>
              {SUPPLIER_CHARGE_KEYS.map(renderField)}
              {renderField("supp_serv_gst")}
              <CompactField
                field={TOTAL_FIELD}
                label="Chrgs + GST"
                value={sideTotal(effective, [...SUPPLIER_CHARGE_KEYS, "supp_serv_gst"])}
                readOnly
                note="Supplier charges plus the supplier's GST on them. A record — not part of the invoice."
                onChange={() => {}}
              />
            </div>
          </div>

          {multiPax && (auto.total_fare !== null || auto.total_amt !== null) && (
            <p className="mt-3 text-[11px] text-gray-500">
              × {paxes.length} pax —
              Total Fare <b className="tabular-nums text-gray-700">{inr((auto.total_fare ?? 0) * paxes.length)}</b>
              {" · "}Invoice Amt <b className="tabular-nums text-gray-700">{inr((auto.total_amt ?? 0) * paxes.length)}</b>
            </p>
          )}

        </Panel>
      </div>

      {/* more details */}
      <div className="bg-white border border-gray-200 rounded-xl">
        <div className="flex items-center gap-1 px-2 py-1.5 flex-wrap">
          <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider px-2">More details</span>
          {moreGroups.map(({ group, fields }) => {
            const filled = fields.filter((f) => !isBlank(draft[f.key])).length
              + (group.custom === "tax_breakup" && draft.tax_breakup ? 1 : 0);
            const active = moreTab === group.id;
            return (
              <button
                key={group.id}
                type="button"
                onClick={() => setMoreTab(active ? null : group.id)}
                className={`px-2.5 py-1 rounded-md text-[11px] font-medium flex items-center gap-1.5 ${
                  active ? "bg-[#1e3a5f] text-white" : "text-gray-600 hover:bg-gray-100"}`}
              >
                {group.label}
                {filled > 0 && (
                  <span className={`px-1 rounded text-[9px] font-bold ${active ? "bg-white/20" : "bg-emerald-100 text-emerald-700"}`}>
                    {filled}
                  </span>
                )}
              </button>
            );
          })}
        </div>
        {/* Kept mounted while hidden so typed values and the tax editor's own rows survive tab switches. */}
        {moreGroups.map(({ group, fields }) => (
          <div key={`${group.id}-${formKey}`} hidden={moreTab !== group.id} className="px-4 pb-3 pt-2 border-t border-gray-100">
            {group.custom === "tax_breakup" ? (
              <div className="max-w-md">
                <TaxBreakupEditor
                  value={draft.tax_breakup as Record<string, number> | null}
                  onChange={(v) => setField("tax_breakup", v)}
                />
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-x-5 gap-y-2">
                {fields.map((f) => renderField(f.key))}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* warnings */}
      {previewWarnings.length > 0 && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-xl px-4 py-2 text-[11px] text-yellow-800 space-y-0.5">
          {previewWarnings.map((w, i) => (
            <div key={i} className="flex items-start gap-2">
              <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-px" />{w}
            </div>
          ))}
        </div>
      )}

      {/* action bar */}
      <div className="bg-white border border-gray-200 rounded-xl px-4 py-2.5 flex items-center gap-2 flex-wrap sticky bottom-3 shadow-sm z-10">
        <Chip label="Rows" value={rows.length > 1 ? `× ${rows.length}` : rows.length === 1 ? "1" : "—"}
          tone={rows.length > 1 ? "amber" : "plain"} />
        <Chip label="ADM/ACM/RA" value={predicted ?? "—"} tone={predicted ? "amber" : "plain"} />
        <Chip label="Segment" value={derived?.segment_type ?? "—"} />
        <Chip label="Invoice" value={derived?.invoice_type ?? "—"} />
        {previewing && <RefreshCw className="w-3 h-3 text-blue-400 animate-spin" />}

        {/* A punched ticket is not a statement — it is listed under All tickets.
            (Behind the scenes it is filed per customer per month; see the
            Statements page for why that batch stays out of sight.) */}
        {!preset && soldToReady && (
          <span className="flex items-center gap-1 text-[11px] text-gray-500 min-w-0">
            <FilePlus className="w-3.5 h-3.5 text-emerald-600 shrink-0" />
            Saved to <b className="text-gray-700">All tickets</b>
          </span>
        )}

        <div className="flex-1 min-w-[8px]" />

        {touched && !soldToReady && (
          <span className="text-[11px] text-red-500">Pick who it was sold to</span>
        )}
        {touched && missingRequired.length > 0 && (
          <span className="text-[11px] text-red-500">
            Required: {missingRequired.map((k) => fieldByKey[k]?.label ?? k).join(", ")}
          </span>
        )}
        {touched && legMalformed && (
          <span className="text-[11px] text-red-500">Each sector is one leg, as DEL/BOM</span>
        )}

        <button
          onClick={clearTicket}
          disabled={draftIsEmpty || saving}
          className="flex items-center gap-1.5 px-3 py-2 border border-gray-200 rounded-lg text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <RotateCcw className="w-3.5 h-3.5" /> Clear
        </button>
        <button
          onClick={() => save(false)}
          disabled={saving}
          title="Save and open the statements list (Ctrl+S)"
          className="flex items-center gap-1.5 px-4 py-2 border border-emerald-600 text-emerald-700 rounded-lg text-sm font-semibold hover:bg-emerald-50 disabled:opacity-50"
        >
          <Save className="w-4 h-4" /> Save
        </button>
        <button
          onClick={() => save(true)}
          disabled={saving}
          title="Save, keep Sold To, and start the next ticket (Ctrl+Enter)"
          className="flex items-center gap-1.5 px-5 py-2 bg-emerald-600 text-white rounded-lg text-sm font-semibold hover:bg-emerald-700 disabled:opacity-50"
        >
          {saving
            ? <><RefreshCw className="w-4 h-4 animate-spin" /> Saving…</>
            : <><CornerDownLeft className="w-4 h-4" /> Save &amp; New</>}
        </button>
      </div>
    </div>
  );
}

// ── Pieces ───────────────────────────────────────────────────────────────────

const SIDE_LABEL = "w-24 shrink-0 text-right text-[11px] font-semibold text-[#1e3a5f] leading-tight";

/**
 * Sold To: Customer / Corporate / Agency, then that party from User master.
 * Agency and Corporate must be a master record; a Customer may be left blank for
 * a walk-in. Locked to the statement's own party when filing into a preset one.
 */
type Masters = { agencies: AgencyRow[]; corporates: Party[]; customers: Party[]; loaded: boolean };

/** The three User-master lists Sold To picks from, fetched once. */
function useMasters(): Masters {
  const [m, setM] = useState<Masters>({ agencies: [], corporates: [], customers: [], loaded: false });
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [a, c, d] = await Promise.allSettled([
        api.get<AgencyRow[]>("/agencies/", { params: { limit: 1000 } }),
        api.get<Party[]>("/corporates/", { params: { limit: 1000 } }),
        api.get<Party[]>("/customers/", { params: { limit: 1000 } }),
      ]);
      if (cancelled) return;
      // None of these endpoints filters is_active by default.
      setM({
        agencies:   a.status === "fulfilled" ? a.value.data.filter((x) => x.is_active) : [],
        corporates: c.status === "fulfilled" ? c.value.data.filter((x) => x.is_active) : [],
        customers:  d.status === "fulfilled" ? d.value.data.filter((x) => x.is_active) : [],
        loaded: true,
      });
    })();
    return () => { cancelled = true; };
  }, []);
  return m;
}

function SoldToRow({ tag, setTag, locked, invalid, masters }: {
  tag: CustomerTag;
  setTag: (t: CustomerTag) => void;
  locked: { soldTo: string | null; name: string } | null;
  invalid?: boolean;
  masters: Masters;
}) {
  const { agencies, corporates, customers, loaded } = masters;
  const [text, setText] = useState("");

  const kind = tag.customerType;
  const options: string[] =
      kind === "agency"    ? agencies.map(agencyLabel)
    : kind === "corporate" ? corporates.map(corporateLabel)
    : kind === "direct"    ? customers.map(customerLabel)
    : [];

  const pickType = (t: CustomerType | null) => {
    setText("");
    setTag(t ? { customerType: t, agencyId: null, corporateId: null, customerId: null, partyName: "" } : EMPTY_TAG);
  };

  const pickName = (v: string) => {
    setText(v);
    if (kind === "agency") {
      const a = agencies.find((x) => agencyLabel(x) === v);
      setTag({ ...tag, agencyId: a?.id ?? null, partyName: a?.name ?? "" });
    } else if (kind === "corporate") {
      const c = corporates.find((x) => corporateLabel(x) === v);
      setTag({ ...tag, corporateId: c?.id ?? null, partyName: c ? ((c.company || "").trim() || partyName(c)) : "" });
    } else if (kind === "direct") {
      const c = customers.find((x) => customerLabel(x) === v);
      setTag({ ...tag, customerId: c?.id ?? null, partyName: v.trim() });
    }
  };

  if (locked) {
    return (
      <div className="sm:col-span-2 flex items-center gap-2 min-w-0">
        <span className={SIDE_LABEL}>Sold To</span>
        <span className="flex-1 min-w-0 px-2 py-1 rounded-md bg-gray-50 border border-gray-200 text-xs text-gray-700 truncate">
          {SOLD_TO.find((s) => s.value === locked.soldTo)?.label ?? "—"} · {locked.name}
          <span className="text-gray-400"> — from the statement</span>
        </span>
      </div>
    );
  }

  const nameMissing = !!invalid && !!kind && kind !== "direct";

  return (
    <div className="sm:col-span-2 flex items-center gap-2 min-w-0">
      <label htmlFor="ct-sold_to" className={SIDE_LABEL}>
        Sold To<span className="text-red-500">*</span>
      </label>
      <select
        id="ct-sold_to"
        value={SOLD_TO.find((s) => s.type === kind)?.value ?? ""}
        onChange={(e) => pickType(SOLD_TO.find((s) => s.value === e.target.value)?.type ?? null)}
        className={`w-28 shrink-0 ${inputCls(!!invalid && !kind)}`}
      >
        <option value="">— select —</option>
        {SOLD_TO.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
      </select>

      {!kind ? (
        <span className="flex-1 min-w-0 px-2 py-1 text-xs text-gray-400 italic">pick Customer, Corporate or Agency</span>
      ) : loaded && options.length === 0 && kind !== "direct" ? (
        <span className="flex-1 min-w-0 px-2 py-1 rounded-md bg-amber-50 border border-amber-200 text-[11px] text-amber-800 truncate">
          None yet — add in{" "}
          <a href={CUSTOMER_TYPE_MASTER[kind].href} className="font-semibold underline">{CUSTOMER_TYPE_MASTER[kind].label}</a>
        </span>
      ) : (
        <PartyCombo
          key={kind}
          value={text}
          options={options}
          onChange={pickName}
          invalid={nameMissing}
          // A walk-in is a typed name, not a pick — say so instead of "no match".
          allowFree={kind === "direct"}
          placeholder={!loaded ? "loading…"
            : kind === "agency" ? "Search agency…" : kind === "corporate" ? "Search corporate…" : "Search customer, or type a walk-in name"}
        />
      )}
    </div>
  );
}

/**
 * Searchable party picker in the app's own dropdown style — the browser's
 * native datalist renders dark and detached from the field. Type to filter;
 * ↑/↓ to move, Enter to pick, Esc to close. Labels read "Name · CODE", so the
 * code is shown muted beside the name.
 */
function PartyCombo({ value, options, onChange, placeholder, invalid, allowFree }: {
  value: string;
  options: string[];
  onChange: (v: string) => void;
  placeholder: string;
  invalid?: boolean;
  allowFree?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  const unique = useMemo(() => [...new Set(options)], [options]);
  const picked = unique.includes(value);
  // Once a name is picked the box shows it in full, so filtering on that text
  // would hide everyone else — reopen to the whole list instead.
  const q = picked ? "" : value.trim().toLowerCase();
  const filtered = q ? unique.filter((o) => o.toLowerCase().includes(q)) : unique;

  const choose = (o: string) => { onChange(o); setOpen(false); };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) { setOpen(true); return; }
      const next = Math.max(0, Math.min(filtered.length - 1, active + (e.key === "ArrowDown" ? 1 : -1)));
      setActive(next);
      listRef.current?.children[next]?.scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter" && open && filtered[active]) {
      e.preventDefault();
      choose(filtered[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div ref={ref} className="relative flex-1 min-w-0">
      <input
        id="ct-sold_to_name"
        value={value}
        placeholder={placeholder}
        autoComplete="off"
        onChange={(e) => { onChange(e.target.value); setActive(0); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onClick={() => setOpen(true)}
        onKeyDown={onKeyDown}
        className={`w-full pr-7 ${inputCls(invalid)} ${picked ? "font-semibold text-gray-800" : ""}`}
      />
      {value ? (
        <button
          type="button"
          tabIndex={-1}
          title="Clear"
          onClick={() => { onChange(""); setOpen(true); }}
          className="absolute right-1.5 top-1/2 -translate-y-1/2 p-0.5 rounded hover:bg-gray-100 text-gray-400"
        >
          <X className="w-3 h-3" />
        </button>
      ) : (
        <ChevronDown className="w-3.5 h-3.5 text-gray-400 absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none" />
      )}

      {open && (
        <div className="absolute z-50 top-full left-0 right-0 mt-1 min-w-[260px] bg-white border border-gray-200 rounded-lg shadow-xl">
          <ul ref={listRef} className="max-h-60 overflow-y-auto py-1">
            {filtered.length === 0 ? (
              <li className="px-3 py-2 text-xs text-gray-400 italic">
                {allowFree && value.trim()
                  ? <>Not in Employee Master — saved as walk-in “{value.trim()}”</>
                  : "No match"}
              </li>
            ) : filtered.map((o, i) => {
              const cut = o.lastIndexOf(" · ");
              const name = cut > 0 ? o.slice(0, cut) : o;
              const code = cut > 0 ? o.slice(cut + 3) : "";
              return (
                <li key={o}>
                  <button
                    type="button"
                    tabIndex={-1}
                    onMouseEnter={() => setActive(i)}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => choose(o)}
                    className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 ${
                      i === active ? "bg-blue-50" : ""} ${o === value ? "text-blue-700 font-semibold" : "text-gray-700"}`}
                  >
                    <span className="truncate">{name}</span>
                    {code && <span className="ml-auto shrink-0 font-mono text-[10px] text-gray-400">{code}</span>}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

/**
 * One line per passenger, in the same side-label rhythm as the fields around it:
 * title, name, and that passenger's own ticket number (each pax is its own ticket).
 */
function PaxRows({ paxes, setPax, showErrors }: {
  paxes: Pax[];
  setPax: (i: number, patch: Partial<Pax>) => void;
  showErrors?: boolean;
}) {
  const multi = paxes.length > 1;
  return (
    <>
      {paxes.map((p, i) => (
        <div key={i} className="sm:col-span-2 flex items-center gap-2 min-w-0">
          <label htmlFor={`ct-pax_name-${i}`} className={SIDE_LABEL}>
            {multi ? `Pax ${i + 1}` : "Pax Name"}
          </label>
          <select
            aria-label={`Pax ${i + 1} title`}
            value={p.title}
            onChange={(e) => setPax(i, { title: e.target.value })}
            className={`w-[72px] shrink-0 ${inputCls()}`}
          >
            <option value="">—</option>
            {PAX_TITLES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
          <input
            id={`ct-pax_name-${i}`}
            value={p.name}
            placeholder="SURNAME/FIRSTNAME"
            onChange={(e) => setPax(i, { name: e.target.value.toUpperCase() })}
            className={`flex-1 min-w-0 ${inputCls()}`}
          />
          <label
            htmlFor={`ct-ticket_number-${i}`}
            className="shrink-0 text-[11px] font-semibold text-[#1e3a5f]"
            title={fieldByKey.ticket_number?.hint}
          >
            Ticket No.<span className="text-red-500">*</span>
          </label>
          <input
            id={`ct-ticket_number-${i}`}
            value={p.ticket}
            onChange={(e) => setPax(i, { ticket: e.target.value })}
            className={`w-36 shrink-0 ${inputCls(!!showErrors && !p.ticket.trim())}`}
          />
        </div>
      ))}
    </>
  );
}

function Panel({ title, color, right, children }: {
  title: string; color: string; right?: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl">
      <div className="px-4 py-1.5 rounded-t-xl flex items-center justify-between" style={{ background: color }}>
        <h2 className="text-[11px] font-bold text-white uppercase tracking-wider">{title}</h2>
        {right}
      </div>
      <div className="px-4 py-3">{children}</div>
    </div>
  );
}

function SubHead({ children }: { children: React.ReactNode }) {
  return <p className="text-[10px] font-bold text-orange-500 uppercase tracking-wider pl-[104px]">{children}</p>;
}

/** Side-labelled input, in the dense one-line style of the desk software. */
function CompactField({
  field, label, value, onChange, invalid, required, readOnly, note, master, gstToggle, emphasis,
}: {
  field: TicketField;
  label?: string;
  value: string | number | null | undefined;
  onChange: (raw: string) => void;
  invalid?: boolean;
  required?: boolean;
  /** A worked-out figure: shown, saved, never typed. */
  readOnly?: boolean;
  /** The one figure that matters — the Invoice Amount — drawn a little heavier. */
  emphasis?: boolean;
  /** For a worked-out figure, how it is worked out. */
  note?: string;
  /** Filled from User master unless typed over. */
  master?: { note: string; manual: boolean; onReset: () => void };
  /** For a typed charge: whether GST is charged on it. */
  gstToggle?: { on: boolean; onToggle: () => void };
}) {
  const id = `ct-${field.key}`;
  const str = value === null || value === undefined ? "" : String(value);
  const isNum = field.type === "number";
  // No spinner arrows — fares are typed, never stepped.
  const cls = `flex-1 min-w-0 ${inputCls(invalid)} ${isNum ? `text-right tabular-nums ${NO_SPIN}` : ""}`;

  if (readOnly) {
    return (
      <div className="flex items-center gap-2 min-w-0" title={note}>
        <span className={SIDE_LABEL}>{label ?? field.label}</span>
        <output
          id={id}
          className={`flex-1 min-w-0 ${INPUT} text-right tabular-nums font-semibold ${
            emphasis ? "border-emerald-300 bg-emerald-100 text-sm" : "border-emerald-100 bg-emerald-50/60"} ${
            typeof value === "number"
              ? (value < 0 ? "text-amber-800" : "text-gray-800")
              : "text-gray-400 font-normal"}`}
        >
          {typeof value === "number"
            ? value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
            : "auto"}
        </output>
      </div>
    );
  }

  return (
    // The catalog hint is still there — as a tooltip, so it costs no height.
    <div className="flex items-center gap-2 min-w-0" title={field.hint}>
      <label htmlFor={id} className={SIDE_LABEL}>
        {label ?? field.label}
        {required && <span className="text-red-500">*</span>}
      </label>
      {field.type === "select" ? (
        <select id={id} value={str} onChange={(e) => onChange(e.target.value)} className={cls}>
          <option value="">—</option>
          {field.options?.map((o) => (
            <option key={o} value={o}>{o.charAt(0).toUpperCase() + o.slice(1)}</option>
          ))}
        </select>
      ) : (
        <input
          id={id}
          type={isNum ? "number" : field.type === "date" ? "date" : "text"}
          step={isNum ? "any" : undefined}
          value={str}
          placeholder={isNum ? "0.00" : field.placeholder}
          onChange={(e) => onChange(e.target.value)}
          // A scroll over a focused number field would silently change the fare.
          onWheel={isNum ? (e) => (e.target as HTMLInputElement).blur() : undefined}
          onClick={field.type === "date"
            ? (e) => { try { (e.target as HTMLInputElement).showPicker(); } catch {} }
            : undefined}
          className={`${cls} ${master && !master.manual ? "bg-blue-50/60 border-blue-100" : ""}`}
        />
      )}
      {gstToggle && (
        <button
          type="button"
          tabIndex={-1}
          onClick={gstToggle.onToggle}
          title={gstToggle.on ? "GST is charged on this. Click for no GST." : "No GST on this. Click to charge GST."}
          className={`shrink-0 px-1.5 py-0.5 rounded border text-[9px] font-bold tracking-wide ${
            gstToggle.on
              ? "bg-emerald-50 border-emerald-200 text-emerald-700"
              : "bg-gray-50 border-gray-200 text-gray-400 line-through"}`}
        >
          +GST
        </button>
      )}
      {/* Filled from User master: a dot while it follows the master, ↺ once typed over. */}
      {master && (
        master.manual ? (
          <button
            type="button"
            tabIndex={-1}
            onClick={master.onReset}
            title={`Typed over. Click to use User master again — ${master.note}`}
            className="shrink-0 p-0.5 rounded text-amber-600 hover:bg-amber-50"
          >
            <RotateCcw className="w-3 h-3" />
          </button>
        ) : (
          <span title={master.note} className="shrink-0 w-4 flex justify-center">
            <span className="w-1.5 h-1.5 rounded-full bg-blue-500" />
          </span>
        )
      )}
    </div>
  );
}

/**
 * One row per flown leg — same data as ItineraryLegsEditor, a fraction of the height.
 * The rows are made from the Sector route typed on the Ticket panel, so the sector
 * itself is shown, not typed, here; class, date and segment type are per leg.
 */
function SectorTable({ legs, legKeys, onChange }: {
  legs: ItineraryLeg[];
  legKeys: string[];
  onChange: (legs: ItineraryLeg[]) => void;
}) {
  const set = (i: number, key: string, value: unknown) =>
    onChange(legs.map((l, j) => (j === i ? { ...l, [key]: value } : l)));

  if (!legs.some((l) => (l.sector ?? "").trim())) {
    return (
      <p className="text-[11px] text-gray-400 italic py-1">
        Type the route in <b className="not-italic text-gray-500">Sector</b> on the Ticket panel — e.g. DEL/BOM/DXB —
        and one row per leg appears here.
      </p>
    );
  }

  return (
    <div>
      <table className="w-full text-xs border-separate border-spacing-x-1.5 border-spacing-y-1 -mx-1.5">
        <thead>
          <tr className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide text-left">
            <th className="w-5 font-semibold">#</th>
            {legKeys.map((k) => (
              <th key={k} className="font-semibold">
                {LEG_HEADERS[k] ?? fieldByKey[k]?.label ?? k}
                {k === "sector" && <span className="text-red-500">*</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {legs.map((leg, i) => {
            const sector = (leg.sector ?? "").trim().toUpperCase();
            const predicted = !(leg.segment_type ?? "").trim() ? predictSegmentType(sector) : null;
            return (
              <tr key={i}>
                <td className="text-[10px] font-bold text-indigo-600">{i + 1}</td>
                {legKeys.map((k) => {
                  const f = fieldByKey[k];
                  const v = (leg[k as keyof ItineraryLeg] ?? "") as string;
                  if (f?.type === "select") {
                    return (
                      <td key={k}>
                        <select
                          value={v}
                          onChange={(e) => set(i, k, coerceFieldValue(f, e.target.value))}
                          className={`w-full ${inputCls()}`}
                        >
                          <option value="">{predicted ? `auto · ${predicted}` : "auto"}</option>
                          {f.options?.map((o) => <option key={o} value={o}>{o}</option>)}
                        </select>
                      </td>
                    );
                  }
                  if (k === "sector") {
                    return (
                      <td key={k} className="w-24">
                        <span
                          title="From the Sector route on the Ticket panel"
                          className={`block ${INPUT} border-indigo-100 bg-indigo-50/60 font-mono font-semibold text-indigo-800`}
                        >
                          {v}
                        </span>
                      </td>
                    );
                  }
                  return (
                    <td key={k} className={k === "booking_class" ? "w-16" : ""}>
                      <input
                        type={f?.type === "date" ? "date" : "text"}
                        value={v}
                        placeholder={k === "booking_class" ? "Y" : undefined}
                        onChange={(e) => {
                          const raw = k === "booking_class" || k === "flight_no"
                            ? e.target.value.toUpperCase() : e.target.value;
                          set(i, k, f ? coerceFieldValue(f, raw) : raw);
                        }}
                        onClick={f?.type === "date"
                          ? (e) => { try { (e.target as HTMLInputElement).showPicker(); } catch {} }
                          : undefined}
                        className={`w-full ${inputCls()}`}
                      />
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** The most airports one route may name — DEL/BOM/DXB/AUH/LHR is four legs. */
const MAX_ROUTE_POINTS = 5;
const EMPTY_ROUTE: string[] = Array(MAX_ROUTE_POINTS).fill("");

/** Complete codes from the first box on, stopping at the first box not yet filled. */
function routeCodes(route: string[]): string[] {
  const out: string[] = [];
  for (const c of route) {
    if (!/^[A-Z]{3}$/.test(c)) break;
    out.push(c);
  }
  return out;
}

/**
 * The Sector route, in the desk software's shape: IXZ / CCU / DED / ___ / ___, then
 * the destination. Each box takes exactly three letters — an airport code — and
 * moves on to the next by itself; Backspace in an empty box goes back one; pasting
 * "DEL/BOM/DXB" (or "DEL BOM DXB") into any box fills the boxes from there.
 */
function RouteInput({ codes, onChange, invalid }: {
  codes: string[];
  onChange: (codes: string[]) => void;
  invalid?: boolean;
}) {
  const refs = useRef<(HTMLInputElement | null)[]>([]);
  // A half-typed code is only flagged once the user has moved off its box.
  const [focused, setFocused] = useState<number | null>(null);
  const focus = (i: number) => refs.current[i]?.focus();
  const clean = (v: string) => v.toUpperCase().replace(/[^A-Z]/g, "");

  const setAt = (i: number, raw: string) => {
    const v = clean(raw).slice(0, 3);
    onChange(codes.map((c, j) => (j === i ? v : c)));
    if (v.length === 3 && i < MAX_ROUTE_POINTS - 1) focus(i + 1);
  };

  const onPaste = (i: number, e: React.ClipboardEvent<HTMLInputElement>) => {
    const parts = e.clipboardData.getData("text").toUpperCase().split(/[^A-Z]+/).filter(Boolean);
    if (parts.length < 2) return;           // a single code pastes normally
    e.preventDefault();
    const next = [...codes];
    parts.slice(0, MAX_ROUTE_POINTS - i).forEach((p, k) => { next[i + k] = p.slice(0, 3); });
    onChange(next);
    focus(Math.min(i + parts.length, MAX_ROUTE_POINTS - 1));
  };

  const complete = routeCodes(codes);
  const destination = complete.length >= 2 ? complete[complete.length - 1] : "";

  return (
    <div className="flex items-center gap-1 min-w-0">
      {codes.map((c, i) => (
        <Fragment key={i}>
          {i > 0 && <span className="text-gray-400 font-mono text-xs">/</span>}
          <input
            ref={(el) => { refs.current[i] = el; }}
            id={`ct-route-${i}`}
            aria-label={`Airport ${i + 1}`}
            value={c}
            placeholder="___"
            maxLength={3}
            autoComplete="off"
            spellCheck={false}
            onChange={(e) => setAt(i, e.target.value)}
            onPaste={(e) => onPaste(i, e)}
            onFocus={(e) => { e.target.select(); setFocused(i); }}
            onBlur={() => setFocused(null)}
            onKeyDown={(e) => {
              if (e.key === "Backspace" && !c && i > 0) { e.preventDefault(); focus(i - 1); }
              if (e.key === "/" ) { e.preventDefault(); if (c.length === 3) focus(i + 1); }
            }}
            className={`w-12 text-center font-mono uppercase tracking-wider ${inputCls(
              (!!invalid && i < 2 && c.length !== 3) || (c !== "" && c.length < 3 && focused !== i),
            )}`}
          />
        </Fragment>
      ))}
      <span
        title="Destination — the last airport of the route"
        className={`ml-1 w-12 text-center ${INPUT} border-gray-200 bg-gray-50 font-mono font-semibold text-gray-700`}
      >
        {destination || " "}
      </span>
    </div>
  );
}

/**
 * The leg rows a route makes — consecutive pairs, DEL/BOM/DXB → DEL/BOM, BOM/DXB.
 * Each leg keeps whatever class, date and segment type the row in its position
 * already had, so retyping the route does not wipe what was entered against it.
 */
function legsFromRoute(route: string[], prev: ItineraryLeg[]): ItineraryLeg[] {
  const codes = routeCodes(route);
  if (codes.length < 2) return [{ ...(prev[0] ?? {}), sector: null }];
  return codes.slice(1).map((dest, i) => ({ ...(prev[i] ?? {}), sector: `${codes[i]}/${dest}` }));
}

function Chip({ label, value, tone = "plain" }: { label: string; value: string; tone?: "plain" | "amber" }) {
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-[11px] ${
      tone === "amber" ? "bg-amber-50 border-amber-200 text-amber-700" : "bg-gray-50 border-gray-200 text-gray-600"}`}>
      <span className="text-[9px] uppercase tracking-wide opacity-60">{label}</span>
      <span className="font-semibold">{value}</span>
    </span>
  );
}
