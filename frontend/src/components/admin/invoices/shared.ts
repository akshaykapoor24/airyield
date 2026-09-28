/**
 * Platform invoices — the Subscriptions page's Invoice column, its Generate form and the
 * per-workspace history. Shapes mirror backend/app/schemas/platform_invoice.py; the rules
 * (numbering, who may charge GST, CGST+SGST vs IGST) live in
 * backend/app/services/platform_invoices.py.
 */
import api from "@/lib/api";
import { GST_STATE_CODES, normaliseTaxId, stateCode } from "@/lib/indiaTax";

export type Party = {
  name: string | null;
  address: string | null;
  city: string | null;
  state: string | null;
  pincode: string | null;
  country: string | null;
  gstin: string | null;
  pan: string | null;
  email: string | null;
  phone: string | null;
};

export type Bank = {
  account_name: string | null;
  account_number: string | null;
  ifsc: string | null;
  bank_name: string | null;
  branch: string | null;
  upi_id: string | null;
};

export type Issuer = Party & { bank: Bank };

/** Quantities and rates travel as strings so 0.1 × 3 stays 0.30 on the way to the server. */
export type Line = { description: string; sac: string | null; quantity: string; unit_price: string; amount?: string };

export type InvoiceStatus = "issued" | "paid" | "cancelled";

export type InvoiceDraft = {
  tenant_id: number;
  next_number: string;
  invoice_date: string;
  due_date: string | null;
  period_from: string | null;
  period_to: string | null;
  gst_rate: number;
  issuer: Issuer;
  bill_to: Party;
  lines: Line[];
  notes: string | null;
};

export type Invoice = {
  id: number;
  invoice_number: string;
  billed_tenant_id: number | null;
  status: InvoiceStatus;
  invoice_date: string;
  due_date: string | null;
  period_from: string | null;
  period_to: string | null;
  issuer: Issuer;
  bill_to: Party;
  gst_treatment: "cgst_sgst" | "igst" | "none";
  place_of_supply: string;
  gst_rate: number;
  line_items: Line[];
  subtotal: number;
  cgst: number;
  sgst: number;
  igst: number;
  total_tax: number;
  grand_total: number;
  notes: string | null;
  paid_at: string | null;
  payment_reference: string | null;
  cancelled_at: string | null;
  cancel_reason: string | null;
  sent_at: string | null;
  sent_to: string | null;
  created_at: string;
  overdue: boolean;
};

export type InvoiceSummary = {
  count: number;
  unpaid_count: number;
  unpaid_total: number;
  overdue_count: number;
  last_number: string | null;
  last_status: InvoiceStatus | null;
  last_date: string | null;
};

export const round2 = (n: number) => Math.round((n + Number.EPSILON) * 100) / 100;

export function lineAmount(l: Line): number {
  const q = Number(l.quantity);
  const r = Number(l.unit_price);
  return Number.isFinite(q) && Number.isFinite(r) ? round2(q * r) : 0;
}

/** Where a party is for GST: the GSTIN's state wins over a typed one, as on the server. */
export function placeCode(p: Pick<Party, "gstin" | "state">): string {
  const fromGstin = normaliseTaxId(p.gstin).slice(0, 2);
  return (fromGstin && GST_STATE_CODES[fromGstin] ? fromGstin : "") || stateCode(p.state);
}

export type Preview = {
  subtotal: number;
  cgst: number;
  sgst: number;
  igst: number;
  total: number;
  /** What the form says about the tax — or why it can't be worked out yet. */
  note: string;
  blocked: boolean;
};

/**
 * A live preview of the server's arithmetic (services/platform_invoices.compute). The
 * server recomputes on save and its figures are the ones stored and printed.
 */
export function preview(lines: Line[], rate: number, issuer: Party, billTo: Party): Preview {
  const subtotal = round2(lines.reduce((s, l) => s + lineAmount(l), 0));
  const base = { subtotal, cgst: 0, sgst: 0, igst: 0, total: subtotal, blocked: false };
  if (!normaliseTaxId(issuer.gstin)) {
    return { ...base, note: "No GSTIN on your company details, so this is a plain invoice with no GST." };
  }
  if (!rate) return { ...base, note: "GST at 0%." };
  const ours = placeCode(issuer);
  const theirs = placeCode(billTo);
  if (!ours || !theirs) {
    return {
      ...base, blocked: true,
      note: "Choose the customer's state (or enter their GSTIN) to decide CGST + SGST or IGST.",
    };
  }
  if (ours !== theirs) {
    const igst = round2((subtotal * rate) / 100);
    return {
      ...base, igst, total: round2(subtotal + igst),
      note: `Inter-state (${GST_STATE_CODES[ours]} → ${GST_STATE_CODES[theirs]}): IGST ${rate}%.`,
    };
  }
  const half = round2((subtotal * rate) / 200);
  return {
    ...base, cgst: half, sgst: half, total: round2(subtotal + 2 * half),
    note: `Within ${GST_STATE_CODES[ours]}: CGST ${rate / 2}% + SGST ${rate / 2}%.`,
  };
}

export function fmtDate(v: string | null): string {
  if (!v) return "—";
  // Date-only strings are calendar dates; parsing them as UTC midnight would show the
  // previous day west of Greenwich.
  const d = /^\d{4}-\d{2}-\d{2}$/.test(v) ? new Date(`${v}T00:00:00`) : new Date(v);
  return d.toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" });
}

export async function downloadInvoicePdf(inv: Pick<Invoice, "id" | "invoice_number">) {
  const res = await api.get(`/subscriptions/invoices/${inv.id}/pdf`, { responseType: "blob" });
  const url = window.URL.createObjectURL(res.data as Blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${inv.invoice_number.replace(/\//g, "-")}.pdf`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

export const STATUS_CHIP: Record<InvoiceStatus, string> = {
  issued: "bg-amber-50 text-amber-700 border-amber-200",
  paid: "bg-green-50 text-green-700 border-green-200",
  cancelled: "bg-gray-50 text-gray-500 border-gray-200",
};
