/**
 * Ticket field catalog — the single source of truth for ticket field metadata.
 *
 * Every consumer derives its list from here instead of writing its own:
 *   - the manual "Create Statement" form   → groupedFieldsFor()
 *   - the upload column-mapping step        → mappingFieldsFor()
 *   - the upload review grid                → reviewColGroups()
 *   - the statement-detail edit modal       → editableFieldsFor()
 *
 * Keys are the canonical names from backend/app/schemas/uploaded_ticket.py
 * (TicketRow) and must stay byte-identical to them — they are posted straight
 * through /tickets/manual/preview to /tickets/upload/confirm.
 */

export type StatementType = "B2B" | "AIRLINE";
export type FieldType = "text" | "date" | "number" | "select";

export type TicketSegment = {
  origin?: string | null;
  destination?: string | null;
  flight_no?: string | null;
  class?: string | null;
  travel_date?: string | null;
};

/** Mirrors TicketRow in backend/app/schemas/uploaded_ticket.py. */
export type TicketRow = {
  row_order:            number;
  booking_ref?:         string | null;
  segment_type?:        string | null;
  invoice_type?:        string | null;
  invoice_no?:          string | null;
  ticket_date?:         string | null;
  last_name?:           string | null;
  first_name?:          string | null;
  sector?:              string | null;
  booking_class?:       string | null;
  departure_datetime?:  string | null;
  gds_pnr?:             string | null;
  airlines_code?:       string | null;
  ticket_number?:       string | null;
  sell_fare?:           number | null;
  sell_tax?:            number | null;
  sell_tax_yq?:         number | null;
  sale_yr?:             number | null;
  sale_k3?:             number | null;
  rei_sell?:            number | null;
  seat_selection?:      number | null;
  excess_baggage?:      number | null;
  meals?:               number | null;
  rfd_sell?:            number | null;
  can_charge?:          number | null;
  booking_fee_sell?:    number | null;
  cgst_sell?:           number | null;
  sgst_sell?:           number | null;
  igst_sell?:           number | null;
  comm_sell?:           number | null;
  adm?:                 number | null;
  incentive_sell?:      number | null;
  dis_sell?:            number | null;
  tds_sell?:            number | null;
  total_amt?:           number | null;
  paid_by_credit_card?: number | null;
  net_amt?:             number | null;
  cc?:                  string | null;
  acc_code?:            string | null;
  sold_to?:             string | null;
  customer_name?:       string | null;
  tour_code?:           string | null;
  split_type?:          string | null;
  adm_acm_ra?:          string | null;
  statement_type?:      string | null;
  pax_name?:            string | null;
  air_pnr?:             string | null;
  pcc?:                 string | null;
  booking_signon?:      string | null;
  booking_pcc?:         string | null;
  booking_agency_name?: string | null;
  ticketing_signon?:    string | null;
  document_type?:       string | null;
  fare_basis?:          string | null;
  fare_const_type?:     string | null;
  base_fare_currency?:  string | null;
  transaction_type?:    string | null;
  exchanged_for?:       string | null;
  stock_control_no?:    string | null;
  stp_no?:              string | null;
  void_date?:           string | null;
  coupon_status?:       string | null;
  refund_type?:         string | null;
  trip_id?:             string | null;
  ai_code?:             string | null;
  value_code?:          string | null;
  multiple_receivables?: string | null;
  wo_tax?:              number | null;
  other_tax?:           number | null;
  comm_percent?:        number | null;
  net_remit?:           number | null;
  net_fare?:            number | null;
  invoice_fare?:        number | null;
  total_refund_amount?: number | null;
  roe?:                 number | null;
  nuc?:                 number | null;
  fop?:                 string | null;
  fop_details?:         string | null;
  cc_auth?:             string | null;
  cc_do_expiry?:        string | null;
  flight_no?:           string | null;
  travel_dt?:           string | null;
  fare_ladder?:         string | null;
  gstn?:                string | null;
  business_phone?:      string | null;
  business_email?:      string | null;
  entity_address?:      string | null;
  tax_breakup?:         Record<string, number> | null;
  segments?:            TicketSegment[] | null;
  airline_name?:        string | null;
  // Server-owned. Present on responses, never posted from a form.
  matched_deal_id?:     number | null;
  matched_deal_type?:   string | null;
  matched_deal_name?:   string | null;
  calculated_incentive?: number | null;
  iata_commission?:     number | null;
  incentive_breakdown?: Record<string, number> | null;
  exclusion_reason?:    string | null;
};

/** What POST /tickets/manual/preview and /tickets/upload/extract return. */
export type TicketExtractionPreview = {
  file_name:         string;
  total_rows:        number;
  rows:              TicketRow[];
  warnings:          string[];
  xls_columns:       string[];
  suggested_mapping: Record<string, string>;
  is_template_match: boolean;
  sample_row:        Record<string, string>;
};

export type FieldGroupId =
  | "identity"
  | "passenger"
  | "itinerary"
  | "fare"
  | "ancillary"
  | "commission"
  | "gst_payment"
  | "accounting"
  | "bsp_doc"
  | "tax_breakup"
  | "segments";

export type TicketField = {
  key: string;
  label: string;
  type: FieldType;
  group: FieldGroupId;
  /** Rendered only for this statement type. Omitted = both. */
  onlyFor?: StatementType;
  options?: string[];
  placeholder?: string;
  /** Shown under the input — reserve it for downstream consequences, not restating the label. */
  hint?: string;
  /** Appears in the upload column-mapping UI. */
  mappable?: boolean;
  /** Required in the upload mapping UI (and to add a manually punched ticket). */
  mapRequired?: boolean;
  /**
   * Mappable only for this statement type. Distinct from `onlyFor`: an AIRLINE
   * file carries Pax_Name rather than separate name columns, so last/first are
   * not offered in its mapping UI — but they still exist on the ticket and stay
   * punchable and editable.
   */
  mapOnlyFor?: StatementType;
  /** Mapping-UI label. Names the alias variants a source column might use. */
  mapLabel?: string;
  /** Appears as a column in the upload review grid. */
  reviewCol?: boolean;
  /** Review-grid header. Terse, because that grid is dense. */
  shortLabel?: string;
  /** Appears in the statement-detail edit modal. */
  editable?: boolean;
};

export type FieldGroup = {
  id: FieldGroupId;
  label: string;
  /** Matches the upload review grid's column-group colours. */
  color: string;
  defaultOpen: boolean;
  onlyFor?: StatementType;
  /** Renders a bespoke editor rather than a grid of inputs. */
  custom?: "tax_breakup" | "segments";
  description?: string;
};

// ── Groups ───────────────────────────────────────────────────────────────────

export const FIELD_GROUPS: FieldGroup[] = [
  { id: "identity",    label: "Ticket & Document",             color: "#1e3a5f", defaultOpen: true,
    description: "Which ticket this is, and what kind of document it settles." },
  { id: "passenger",   label: "Passenger & Customer",          color: "#1e3a5f", defaultOpen: true,
    description: "Who flew, and who we billed." },
  { id: "itinerary",   label: "Itinerary",                     color: "#4f46e5", defaultOpen: true,
    description: "Sector, class and dates — these drive deal matching." },
  { id: "fare",        label: "Fare & Taxes",                  color: "#059669", defaultOpen: true,
    description: "The published fare breakdown. Basic, YQ and YR feed incentive calculation." },
  { id: "commission",  label: "Commission & Settlement",       color: "#059669", defaultOpen: false,
    description: "Commission and discount as received — not the incentive we calculate." },
  { id: "ancillary",   label: "Ancillaries & Service Charges", color: "#059669", defaultOpen: false,
    description: "Seat, baggage and meals are separate incentive bases." },
  { id: "gst_payment", label: "GST & Payment",                 color: "#9333ea", defaultOpen: false },
  { id: "accounting",  label: "Accounting & Codes",            color: "#9333ea", defaultOpen: false,
    description: "Tour code is read by payout inclusion/exclusion rules." },
  { id: "bsp_doc",     label: "BSP Document Control",          color: "#9333ea", defaultOpen: false,
    onlyFor: "AIRLINE" },
  { id: "tax_breakup", label: "Tax Breakup",                   color: "#059669", defaultOpen: false,
    onlyFor: "AIRLINE", custom: "tax_breakup",
    description: "One row per tax code, as printed on the BSP statement." },
  { id: "segments",    label: "Segments",                      color: "#4f46e5", defaultOpen: false,
    onlyFor: "AIRLINE", custom: "segments",
    description: "Derived from sector, flight number, travel date and class." },
];

// ── Fields ───────────────────────────────────────────────────────────────────
// 84 plain fields. Plus the two JSONB fields (tax_breakup, segments) driven by
// the custom group editors, plus the 11 server-owned fields listed below, that
// accounts for all 97 TicketRow fields.

export const TICKET_FIELDS: TicketField[] = [
  // ── Ticket & Document ─────────────────────────────────────────────────────
  { key: "ticket_number",      label: "Ticket Number", shortLabel: "Ticket #",   type: "text", group: "identity", mappable: true, mapRequired: true, reviewCol: true, editable: true,
    placeholder: "0982512345678",
    hint: "Prefix decides ADM/ACM/RA classification: 400… → RA, 6… → ADM, 8… → ACM." },
  { key: "airlines_code",      label: "Airline Code",    type: "text", group: "identity", mappable: true, mapRequired: true, reviewCol: true, editable: true,
    placeholder: "AI",
    hint: "Must resolve in the airline master or the ticket can never match a deal." },
  { key: "airline_name",       label: "Airline Name",    type: "text", group: "identity", mappable: true, reviewCol: true, editable: true },
  { key: "ticket_date",        label: "Ticket Date",     type: "date", group: "identity", mappable: true, reviewCol: true, editable: true },
  { key: "invoice_type",       label: "Invoice Type",    type: "select", group: "identity", mappable: true, reviewCol: true, editable: true,
    options: ["Invoice", "Sales", "Flown", "Credit Note", "Refund"],
    hint: "Credit Note and Refund reverse a prior ticket instead of earning incentive." },
  { key: "invoice_no",         label: "Invoice No",      type: "text", group: "identity", mappable: true, reviewCol: true, editable: true },
  { key: "gds_pnr",            label: "GDS / Gal PNR", shortLabel: "GDS PNR",   type: "text", group: "identity", mappable: true, reviewCol: true, editable: true },
  { key: "booking_ref",        label: "Booking Ref",     type: "text", group: "identity", onlyFor: "B2B", mappable: true, reviewCol: true, editable: true },
  { key: "air_pnr",            label: "Air PNR",         type: "text", group: "identity", onlyFor: "AIRLINE", mappable: true, editable: true },
  { key: "document_type",      label: "Document Type",   type: "text", group: "identity", onlyFor: "AIRLINE", mappable: true, editable: true },
  { key: "transaction_type",   label: "Transaction Type", type: "select", group: "identity", onlyFor: "AIRLINE", mappable: true, editable: true,
    options: ["TKTT", "RFND", "ADMD", "ACMD", "CANX", "VOID"],
    hint: "Sets invoice type automatically: TKTT → Invoice, the rest → Credit Note." },

  // ── Passenger & Customer ──────────────────────────────────────────────────
  { key: "pax_name",           label: "Pax Name",        type: "text", group: "passenger", onlyFor: "AIRLINE", mappable: true, editable: true,
    placeholder: "SHARMA/RAHUL MR",
    hint: "Split on / into last and first name." },
  { key: "last_name",          label: "Last Name", mapOnlyFor: "B2B",       type: "text", group: "passenger", mappable: true, reviewCol: true, editable: true },
  { key: "first_name",         label: "First Name", mapOnlyFor: "B2B",      type: "text", group: "passenger", mappable: true, reviewCol: true, editable: true },
  { key: "customer_name",      label: "Customer / Client", shortLabel: "Customer Name", type: "text", group: "passenger", mappable: true, reviewCol: true, editable: true },
  { key: "sold_to",            label: "Sold To",         type: "select", group: "passenger", onlyFor: "B2B", mappable: true, reviewCol: true, editable: true,
    options: ["customer", "agency"] },
  { key: "gstn",               label: "GSTN",            type: "text", group: "passenger", onlyFor: "AIRLINE", mappable: true, editable: true },
  { key: "business_phone",     label: "Business Phone",  type: "text", group: "passenger", onlyFor: "AIRLINE", editable: true },
  { key: "business_email",     label: "Business Email",  type: "text", group: "passenger", onlyFor: "AIRLINE", editable: true },
  { key: "entity_address",     label: "Entity Address",  type: "text", group: "passenger", onlyFor: "AIRLINE", editable: true },

  // ── Itinerary ─────────────────────────────────────────────────────────────
  { key: "sector",             label: "Sector", mapLabel: "Sector / Sectors",          type: "text", group: "itinerary", mappable: true, mapRequired: true, reviewCol: true, editable: true,
    placeholder: "DEL/BOM",
    hint: "Three or more airports splits the ticket into one row per leg." },
  { key: "booking_class",      label: "Booking Class", shortLabel: "Class",   type: "text", group: "itinerary", mappable: true, reviewCol: true, editable: true,
    placeholder: "Y",
    hint: "Leave blank and deal matching treats this ticket as Economy." },
  { key: "departure_datetime", label: "Departure Date", mapLabel: "Departure Date/Time", shortLabel: "Departure",  type: "date", group: "itinerary", mappable: true, reviewCol: true, editable: true,
    hint: "Used as the travel date for deal validity; falls back to ticket date." },
  { key: "segment_type",       label: "Segment Type",    type: "select", group: "itinerary", mappable: true, reviewCol: true, editable: true,
    options: ["Domestic", "International"],
    hint: "Filters Domestic/International incentives." },
  { key: "flight_no",          label: "Flight No",       type: "text", group: "itinerary", onlyFor: "AIRLINE", mappable: true, editable: true,
    placeholder: "AI-101 AI-102" },
  { key: "travel_dt",          label: "Travel Dt",       type: "text", group: "itinerary", onlyFor: "AIRLINE", mappable: true, editable: true,
    placeholder: "16MAY 24MAY",
    hint: "First token fills the departure date when it is blank. A bare day+month resolves to the current year." },
  { key: "fare_basis",         label: "Fare Basis",      type: "text", group: "itinerary", onlyFor: "AIRLINE", mappable: true, editable: true },
  { key: "fare_const_type",    label: "Fare Const Type", type: "text", group: "itinerary", onlyFor: "AIRLINE", mappable: true, editable: true },

  // ── Fare & Taxes ──────────────────────────────────────────────────────────
  { key: "sell_fare",          label: "Basic / Sell Fare", mapLabel: "Sell / Base Fare", shortLabel: "Sell Fare", type: "number", group: "fare", mappable: true, reviewCol: true, editable: true,
    hint: "The primary incentive base." },
  { key: "sell_tax",           label: "Total Tax", mapLabel: "Sell Tax / Total Tax", shortLabel: "Sell Tax",       type: "number", group: "fare", mappable: true, reviewCol: true, editable: true },
  { key: "sell_tax_yq",        label: "YQ Tax", mapLabel: "Tax YQ", shortLabel: "Tax YQ",          type: "number", group: "fare", mappable: true, reviewCol: true, editable: true,
    hint: "Added to the incentive base on Basic+YQ deals." },
  { key: "sale_yr",            label: "YR Tax", mapLabel: "Sale YR", shortLabel: "Sale YR",          type: "number", group: "fare", mappable: true, reviewCol: true, editable: true,
    hint: "Added to the incentive base on Basic+YQ+YR deals." },
  { key: "sale_k3",            label: "K3 Tax", mapLabel: "Sale K3", shortLabel: "Sale K3",          type: "number", group: "fare", mappable: true, reviewCol: true, editable: true },
  { key: "wo_tax",             label: "WO Tax",          type: "number", group: "fare", onlyFor: "AIRLINE", mappable: true, editable: true },
  { key: "other_tax",          label: "Other Taxes",     type: "number", group: "fare", onlyFor: "AIRLINE", mappable: true, editable: true },
  { key: "total_amt",          label: "Total Fare", mapLabel: "Total Fare / Amt", shortLabel: "Total Amt",      type: "number", group: "fare", mappable: true, reviewCol: true, editable: true },
  { key: "net_amt",            label: "Net Amount", mapLabel: "Net AMT / Net Remit", shortLabel: "Net AMT",      type: "number", group: "fare", mappable: true, reviewCol: true, editable: true },
  { key: "net_fare",           label: "Net Fare",        type: "number", group: "fare", onlyFor: "AIRLINE", mappable: true, editable: true },
  { key: "net_remit",          label: "Net Remit",       type: "number", group: "fare", onlyFor: "AIRLINE", editable: true },
  { key: "invoice_fare",       label: "Invoice Fare",    type: "number", group: "fare", onlyFor: "AIRLINE", editable: true },
  { key: "total_refund_amount", label: "Total Refund Amount", type: "number", group: "fare", onlyFor: "AIRLINE", editable: true },
  { key: "base_fare_currency", label: "Fare Currency",   type: "text", group: "fare", onlyFor: "AIRLINE", editable: true, placeholder: "INR" },
  { key: "roe",                label: "ROE",             type: "number", group: "fare", onlyFor: "AIRLINE", mappable: true, editable: true },
  { key: "nuc",                label: "NUC",             type: "number", group: "fare", onlyFor: "AIRLINE", mappable: true, editable: true },
  { key: "fare_ladder",        label: "Fare Ladder",     type: "text", group: "fare", onlyFor: "AIRLINE", editable: true },

  // ── Commission & Settlement ───────────────────────────────────────────────
  { key: "comm_sell",          label: "Commission Amount", mapLabel: "Comm Sell / Comm Amt", shortLabel: "Comm Sell", type: "number", group: "commission", mappable: true, reviewCol: true, editable: true,
    hint: "Commission received from the supplier. Zeroed automatically on a credit note." },
  { key: "comm_percent",       label: "Commission (%)", mapLabel: "Comm (%)",  type: "number", group: "commission", onlyFor: "AIRLINE", mappable: true, editable: true },
  { key: "incentive_sell",     label: "Incentive Received", mapLabel: "Incentive Sell", shortLabel: "Incentive", type: "number", group: "commission", onlyFor: "B2B", mappable: true, reviewCol: true, editable: true,
    hint: "What the supplier already paid. The incentive we calculate is separate." },
  { key: "dis_sell",           label: "Discount", mapLabel: "Dis Sell", shortLabel: "Dis Sell",        type: "number", group: "commission", onlyFor: "B2B", mappable: true, reviewCol: true, editable: true },
  { key: "tds_sell",           label: "TDS", mapLabel: "TDS Sell", shortLabel: "TDS Sell",             type: "number", group: "commission", onlyFor: "B2B", mappable: true, reviewCol: true, editable: true },
  { key: "adm",               label: "ADM / Recall", mapLabel: "ADM", shortLabel: "ADM",     type: "number", group: "commission", onlyFor: "B2B", mappable: true, reviewCol: true, editable: true },
  { key: "refund_type",        label: "Refund Type",     type: "text", group: "commission", onlyFor: "AIRLINE", editable: true },

  // ── Ancillaries & Service Charges ─────────────────────────────────────────
  { key: "seat_selection",     label: "Seat Selection", shortLabel: "Seat Sel.",  type: "number", group: "ancillary", onlyFor: "B2B", mappable: true, reviewCol: true, editable: true,
    hint: "A separate ancillary incentive base." },
  { key: "excess_baggage",     label: "Excess Baggage", shortLabel: "Excess Bag.",  type: "number", group: "ancillary", onlyFor: "B2B", mappable: true, reviewCol: true, editable: true,
    hint: "A separate ancillary incentive base." },
  { key: "meals",              label: "Meals",           type: "number", group: "ancillary", onlyFor: "B2B", mappable: true, reviewCol: true, editable: true,
    hint: "A separate ancillary incentive base." },
  { key: "rei_sell",           label: "REI Sell",        type: "number", group: "ancillary", onlyFor: "B2B", mappable: true, reviewCol: true, editable: true },
  { key: "booking_fee_sell",   label: "Booking Fee", mapLabel: "Booking Fee Sell",     type: "number", group: "ancillary", onlyFor: "B2B", mappable: true, reviewCol: true, editable: true },
  { key: "can_charge",         label: "Cancellation Charge", mapLabel: "CAN Charge", shortLabel: "CAN Charge", type: "number", group: "ancillary", onlyFor: "B2B", mappable: true, reviewCol: true, editable: true },
  { key: "rfd_sell",           label: "RFD Sell",        type: "number", group: "ancillary", onlyFor: "B2B", mappable: true, reviewCol: true, editable: true },

  // ── GST & Payment ─────────────────────────────────────────────────────────
  { key: "cgst_sell",          label: "CGST", mapLabel: "CGST Sell",            type: "number", group: "gst_payment", onlyFor: "B2B", mappable: true, reviewCol: true, editable: true },
  { key: "sgst_sell",          label: "SGST", mapLabel: "SGST Sell",            type: "number", group: "gst_payment", onlyFor: "B2B", mappable: true, reviewCol: true, editable: true },
  { key: "igst_sell",          label: "IGST", mapLabel: "IGST Sell",            type: "number", group: "gst_payment", onlyFor: "B2B", mappable: true, reviewCol: true, editable: true },
  { key: "paid_by_credit_card", label: "Paid By Credit Card", shortLabel: "Paid CC", type: "number", group: "gst_payment", onlyFor: "B2B", mappable: true, reviewCol: true, editable: true },
  { key: "cc",                 label: "CC",              type: "text", group: "gst_payment", onlyFor: "B2B", mappable: true, reviewCol: true, editable: true },
  { key: "fop",                label: "FOP",             type: "text", group: "gst_payment", onlyFor: "AIRLINE", mappable: true, editable: true },
  { key: "fop_details",        label: "FOP Details",     type: "text", group: "gst_payment", onlyFor: "AIRLINE", mappable: true, editable: true },
  { key: "cc_auth",            label: "CC Auth",         type: "text", group: "gst_payment", onlyFor: "AIRLINE", editable: true },
  { key: "cc_do_expiry",       label: "CC / DO Expiry",  type: "text", group: "gst_payment", onlyFor: "AIRLINE", editable: true },

  // ── Accounting & Codes ────────────────────────────────────────────────────
  { key: "acc_code",           label: "Acc Code", mapLabel: "Acc Code / AC_ACCT",        type: "text", group: "accounting", mappable: true, reviewCol: true, editable: true },
  { key: "tour_code",          label: "Tour / Deal Code", mapLabel: "Tour Code", type: "text", group: "accounting", mappable: true, editable: true,
    hint: "Read by payout inclusion and exclusion rules for tour and corporate fares." },
  { key: "ai_code",            label: "AI Code",         type: "text", group: "accounting", onlyFor: "AIRLINE", editable: true },
  { key: "value_code",         label: "Value Code",      type: "text", group: "accounting", onlyFor: "AIRLINE", editable: true },
  { key: "pcc",                label: "PCC",             type: "text", group: "accounting", onlyFor: "AIRLINE", mappable: true, editable: true },
  { key: "booking_pcc",        label: "Booking PCC",     type: "text", group: "accounting", onlyFor: "AIRLINE", editable: true },
  { key: "booking_signon",     label: "Booking Sign-on", type: "text", group: "accounting", onlyFor: "AIRLINE", mappable: true, editable: true },
  { key: "ticketing_signon",   label: "Ticketing Sign-on", type: "text", group: "accounting", onlyFor: "AIRLINE", mappable: true, editable: true },
  { key: "booking_agency_name", label: "Booking Agency Name", type: "text", group: "accounting", onlyFor: "AIRLINE", mappable: true, editable: true },

  // ── BSP Document Control (AIRLINE only) ───────────────────────────────────
  { key: "stock_control_no",   label: "Stock Control No", type: "text", group: "bsp_doc", onlyFor: "AIRLINE", editable: true },
  { key: "stp_no",             label: "STP No",          type: "text", group: "bsp_doc", onlyFor: "AIRLINE", editable: true },
  { key: "exchanged_for",      label: "Exchanged For / Re-Iss", type: "text", group: "bsp_doc", onlyFor: "AIRLINE", editable: true },
  { key: "void_date",          label: "Void / Refund Date", type: "date", group: "bsp_doc", onlyFor: "AIRLINE", editable: true },
  { key: "coupon_status",      label: "Coupon Status",   type: "text", group: "bsp_doc", onlyFor: "AIRLINE", editable: true },
  { key: "trip_id",            label: "Trip ID",         type: "text", group: "bsp_doc", onlyFor: "AIRLINE", editable: true },
  { key: "multiple_receivables", label: "Multiple Receivables", type: "text", group: "bsp_doc", onlyFor: "AIRLINE", editable: true },
];

/**
 * TicketRow fields the server owns. Never rendered as an input:
 *   row_order       — assigned from the buffer position; not a DB column
 *   statement_type  — comes from the statement panel
 *   split_type      — set by the multi-sector split
 *   adm_acm_ra      — derived from the ticket number at confirm
 *   the rest        — written by run-calculation
 * POST /tickets/manual/preview strips these from the payload.
 */
export const SERVER_OWNED_FIELDS = [
  "row_order", "statement_type", "split_type", "adm_acm_ra",
  "matched_deal_id", "matched_deal_type", "matched_deal_name",
  "calculated_incentive", "iata_commission", "incentive_breakdown",
  "exclusion_reason",
] as const;

// ── Derived selectors ────────────────────────────────────────────────────────

export const fieldByKey: Record<string, TicketField> = Object.fromEntries(
  TICKET_FIELDS.map((f) => [f.key, f]),
);

export const fieldsFor = (t: StatementType): TicketField[] =>
  TICKET_FIELDS.filter((f) => !f.onlyFor || f.onlyFor === t);

export const groupsFor = (t: StatementType): FieldGroup[] =>
  FIELD_GROUPS.filter((g) => !g.onlyFor || g.onlyFor === t);

/** Groups paired with their fields, dropping any group left empty for this type. */
export const groupedFieldsFor = (
  t: StatementType,
): { group: FieldGroup; fields: TicketField[] }[] => {
  const active = fieldsFor(t);
  return groupsFor(t)
    .map((group) => ({ group, fields: active.filter((f) => f.group === group.id) }))
    .filter(({ group, fields }) => fields.length > 0 || !!group.custom);
};

export const mappingFieldsFor = (t: StatementType): TicketField[] =>
  fieldsFor(t).filter((f) => f.mappable && (!f.mapOnlyFor || f.mapOnlyFor === t));

/**
 * Fields the statement-detail edit modal should offer for one ticket.
 *
 * Scoped to the ticket's statement type, but a field carrying a value is always
 * included even when the other type owns it — hiding populated data would make
 * it permanently uneditable.
 */
export const editableFieldsForTicket = (
  statementType: string | null | undefined,
  ticket: Record<string, unknown>,
): TicketField[] => {
  const t: StatementType = statementType === "AIRLINE" ? "AIRLINE" : "B2B";
  return TICKET_FIELDS.filter(
    (f) => f.editable && (!f.onlyFor || f.onlyFor === t || ticket[f.key] != null),
  );
};

/**
 * The upload review grid's four colour-coded column groups.
 *
 * Ordering is explicit rather than derived from FIELD_GROUPS because the grid
 * bundles fields differently from the punch form — it is one wide table, not a
 * stack of cards.
 */
const REVIEW_GROUP_KEYS: { label: string; color: string; keys: string[] }[] = [
  { label: "Passenger & Booking", color: "#1e3a5f", keys: [
    "booking_ref", "segment_type", "invoice_type", "invoice_no", "ticket_date",
    "last_name", "first_name",
  ]},
  { label: "Flight Info", color: "#4f46e5", keys: [
    "sector", "booking_class", "departure_datetime", "gds_pnr", "airlines_code",
    "airline_name", "ticket_number",
  ]},
  { label: "Financial", color: "#059669", keys: [
    "sell_fare", "sell_tax", "sell_tax_yq", "sale_yr", "sale_k3", "rei_sell",
    "seat_selection", "excess_baggage", "meals", "rfd_sell", "can_charge",
    "booking_fee_sell", "cgst_sell", "sgst_sell", "igst_sell", "comm_sell",
    "adm", "incentive_sell", "dis_sell", "tds_sell", "total_amt",
    "paid_by_credit_card", "net_amt",
  ]},
  { label: "Account", color: "#9333ea", keys: [
    "cc", "acc_code", "sold_to", "customer_name",
  ]},
];

export type ReviewCol = { key: string; label: string; type: "text" | "date" | "number" };
export type ReviewColGroup = { label: string; color: string; cols: ReviewCol[] };

export const reviewColGroups = (): ReviewColGroup[] =>
  REVIEW_GROUP_KEYS.map(({ label, color, keys }) => ({
    label,
    color,
    cols: keys.map((k) => {
      const f = fieldByKey[k];
      return {
        key: k,
        label: f.shortLabel ?? f.label,
        // The grid has no select control — a select field renders as free text there.
        type: (f.type === "select" ? "text" : f.type) as ReviewCol["type"],
      };
    }),
  }));

/** The three fields the upload mapping step requires, and that a punched ticket needs. */
export const REQUIRED_KEYS: string[] = TICKET_FIELDS.filter((f) => f.mapRequired).map((f) => f.key);

export const NUMERIC_KEYS: Set<string> = new Set(
  TICKET_FIELDS.filter((f) => f.type === "number").map((f) => f.key),
);

export const DATE_KEYS: Set<string> = new Set(
  TICKET_FIELDS.filter((f) => f.type === "date").map((f) => f.key),
);

// ── Shared helpers ───────────────────────────────────────────────────────────

export const MANUAL_ENTRY_FILE_NAME = "Manual Entry";

/** Airline agencies are a fixed list; B2B agencies come from the supplier master. */
export const AIRLINE_AGENCIES = ["BSP", "NDC", "TGHMPR", "TGQ"] as const;

/** Coerce a raw input value to what the API expects for this field. */
export function coerceFieldValue(field: TicketField, raw: string): string | number | null {
  if (raw === "") return null;
  if (field.type === "number") {
    const n = parseFloat(raw);
    return Number.isFinite(n) ? n : null;
  }
  if (field.key === "sold_to") return raw.trim().toLowerCase();
  return raw;
}

/**
 * Mirror of _classify_ticket in backend/app/api/v1/tickets.py, for showing the
 * user what the server will derive. Display only — never posted.
 */
export function predictAdmAcmRa(ticketNumber: string | null | undefined): "RA" | "ADM" | "ACM" | null {
  const tn = (ticketNumber ?? "").trim();
  if (!tn) return null;
  if (tn.startsWith("400")) return "RA";
  const stripped = tn.replace(/^0+/, "") || "0";
  if (stripped.startsWith("6")) return "ADM";
  if (stripped.startsWith("8")) return "ACM";
  return null;
}

export const SECTOR_RE: Record<StatementType, RegExp> = {
  B2B: /^[A-Z]{3}(\/[A-Z]{3})+$/,
  AIRLINE: /^[A-Z]{3}\/[A-Z]{3}( +[A-Z]{3}\/[A-Z]{3})*$/,
};

export const inr = (v: number | string | null | undefined): string => {
  if (v === null || v === undefined || v === "") return "—";
  const n = typeof v === "number" ? v : parseFloat(String(v));
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};
