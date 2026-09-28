"use client";

import { useEffect, useMemo, useState } from "react";
import { Building2, ChevronDown, ChevronRight, Info, Plus, Trash2 } from "lucide-react";
import api from "@/lib/api";
import { rupees } from "@/lib/money";
import { STATE_NAMES, gstinError, normaliseTaxId, panError } from "@/lib/indiaTax";
import { INPUT, LABEL, ModalShell, apiError } from "@/components/userMaster/shared";
import { fmtBytes, fmtUsd, type ResourceUsage } from "@/components/admin/UsageCells";
import {
  lineAmount, preview, type Invoice, type InvoiceDraft, type Issuer, type Line, type Party,
} from "./shared";

const CELL = "w-full border border-gray-200 rounded-md px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-sky-400 bg-white";
const GST_RATES = [0, 5, 12, 18, 28];

type Form = Omit<InvoiceDraft, "tenant_id" | "next_number">;

function Field({ label, children, error, span = 1 }: {
  label: string; children: React.ReactNode; error?: string; span?: 1 | 2;
}) {
  return (
    <div className={span === 2 ? "col-span-2" : undefined}>
      <label className={LABEL}>{label}</label>
      {children}
      {error && <p className="mt-1 text-[10px] text-red-500">{error}</p>}
    </div>
  );
}

function Section({ title, children, aside }: { title: string; children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-bold text-gray-800">{title}</h3>
        {aside}
      </div>
      {children}
    </section>
  );
}

/** A party's name / address / tax ids, shared by Bill to and Your company. */
function PartyFields({ value, onChange, requireState }: {
  value: Party; onChange: (p: Party) => void; requireState?: boolean;
}) {
  const set = (k: keyof Party) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    onChange({ ...value, [k]: e.target.value });
  const gstin = normaliseTaxId(value.gstin);
  const pan = normaliseTaxId(value.pan);
  return (
    <div className="grid grid-cols-2 gap-3">
      <Field label="Name *"><input className={INPUT} value={value.name ?? ""} onChange={set("name")} /></Field>
      <Field label="Email"><input className={INPUT} value={value.email ?? ""} onChange={set("email")} /></Field>
      <Field label="GSTIN" error={gstinError(gstin, { pan, state: value.state ?? "" })}>
        <input className={INPUT} value={value.gstin ?? ""} onChange={set("gstin")} placeholder="Leave empty if unregistered" />
      </Field>
      <Field label="PAN" error={panError(pan)}>
        <input className={INPUT} value={value.pan ?? ""} onChange={set("pan")} />
      </Field>
      <Field label="Address" span={2}>
        <textarea className={INPUT} rows={2} value={value.address ?? ""} onChange={set("address")} />
      </Field>
      <Field label="City"><input className={INPUT} value={value.city ?? ""} onChange={set("city")} /></Field>
      <Field label={requireState ? "State *" : "State"}>
        <select className={INPUT} value={value.state ?? ""} onChange={set("state")}>
          <option value="">Select state…</option>
          {/* A stored state outside the list still shows, so it is visible and fixable. */}
          {value.state && !STATE_NAMES.includes(value.state) && <option value={value.state}>{value.state}</option>}
          {STATE_NAMES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </Field>
      <Field label="Pincode"><input className={INPUT} value={value.pincode ?? ""} onChange={set("pincode")} /></Field>
      <Field label="Phone"><input className={INPUT} value={value.phone ?? ""} onChange={set("phone")} /></Field>
    </div>
  );
}

/**
 * Subscriptions → Generate invoice. Opens on the server's draft: the workspace's own
 * profile as Bill to, last month's lines for this workspace, and the platform's company
 * and bank details from the last invoice raised — so a monthly invoice is two clicks.
 */
export default function GenerateInvoiceModal({ tenantId, tenantName, usage, onClose, onCreated }: {
  tenantId: number;
  tenantName: string;
  /** This workspace's metered usage, shown as a pricing reference. */
  usage: ResourceUsage | null;
  onClose: () => void;
  onCreated: (inv: Invoice) => void;
}) {
  const [nextNumber, setNextNumber] = useState("");
  const [form, setForm] = useState<Form | null>(null);
  const [loadError, setLoadError] = useState("");
  const [showIssuer, setShowIssuer] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    api.get<InvoiceDraft>(`/subscriptions/${tenantId}/invoice-draft`)
      .then(({ data }) => {
        if (!live) return;
        const { tenant_id: _t, next_number, ...rest } = data;
        void _t;
        setNextNumber(next_number);
        setForm(rest);
        // First invoice ever: the company details have never been filled in, so open them.
        setShowIssuer(!data.issuer.state && !data.issuer.gstin);
      })
      .catch((e) => live && setLoadError(apiError(e)));
    return () => { live = false; };
  }, [tenantId]);

  const totals = useMemo(
    () => (form ? preview(form.lines, form.gst_rate, form.issuer, form.bill_to) : null),
    [form],
  );

  if (!form || !totals) {
    return (
      <ModalShell title={`Generate invoice — ${tenantName}`} onClose={onClose} wide>
        <p className={`text-xs py-8 text-center ${loadError ? "text-red-500" : "text-gray-400"}`}>
          {loadError || "Loading…"}
        </p>
      </ModalShell>
    );
  }

  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm({ ...form, [k]: v });
  const setLine = (i: number, patch: Partial<Line>) =>
    set("lines", form.lines.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const issuer = form.issuer;
  const setIssuer = (p: Partial<Issuer>) => set("issuer", { ...issuer, ...p });

  const problem =
    !form.bill_to.name?.trim() ? "Enter who the invoice is for." :
    !issuer.name?.trim() ? "Enter your company name." :
    form.lines.some((l) => !l.description.trim()) ? "Every line needs a description." :
    totals.subtotal <= 0 ? "The invoice total must be more than zero." :
    totals.blocked ? totals.note : "";

  const submit = async () => {
    setSaving(true);
    setError("");
    try {
      const { data } = await api.post<Invoice>(`/subscriptions/${tenantId}/invoices`, {
        ...form,
        due_date: form.due_date || null,
        period_from: form.period_from || null,
        period_to: form.period_to || null,
        notes: form.notes?.trim() || null,
      });
      onCreated(data);
    } catch (e) {
      setError(apiError(e));
    } finally {
      setSaving(false);
    }
  };

  const bank = issuer.bank;
  const issuerSummary = [issuer.name, issuer.gstin && `GSTIN ${issuer.gstin}`,
    bank.account_number && `A/c ••${bank.account_number.slice(-4)}`, bank.upi_id].filter(Boolean).join(" · ");

  return (
    <ModalShell title={`Generate invoice — ${tenantName}`} onClose={onClose} wide>
      <div className="space-y-6">
        {/* Number and dates */}
        <div className="grid grid-cols-4 gap-3">
          <div className="col-span-4 flex items-center justify-between rounded-lg bg-violet-50 border border-violet-100 px-3 py-2">
            <span className="text-[11px] text-violet-700">
              Invoice <b>{nextNumber}</b>
              <span className="text-violet-400"> · the final number is assigned when you generate</span>
            </span>
          </div>
          <Field label="Invoice date *">
            <input type="date" className={INPUT} value={form.invoice_date} onChange={(e) => set("invoice_date", e.target.value)} />
          </Field>
          <Field label="Due date">
            <input type="date" className={INPUT} value={form.due_date ?? ""} onChange={(e) => set("due_date", e.target.value)} />
          </Field>
          <Field label="Period from">
            <input type="date" className={INPUT} value={form.period_from ?? ""} onChange={(e) => set("period_from", e.target.value)} />
          </Field>
          <Field label="Period to">
            <input type="date" className={INPUT} value={form.period_to ?? ""} onChange={(e) => set("period_to", e.target.value)} />
          </Field>
        </div>

        <Section title="Bill to">
          <PartyFields value={form.bill_to} onChange={(p) => set("bill_to", p)} requireState />
        </Section>

        <Section
          title="Line items"
          aside={
            <button
              onClick={() => set("lines", [...form.lines, { description: "", sac: form.lines[0]?.sac ?? null, quantity: "1", unit_price: "0" }])}
              className="inline-flex items-center gap-1 text-[11px] font-medium text-violet-700 hover:text-violet-900"
            >
              <Plus className="w-3 h-3" /> Add line
            </button>
          }
        >
          {usage && (usage.ai.calls > 0 || usage.files.bytes > 0) && (
            <div className="flex items-start gap-2 rounded-lg bg-gray-50 border border-gray-100 px-3 py-2 text-[11px] text-gray-500">
              <Info className="w-3.5 h-3.5 mt-0.5 shrink-0 text-gray-400" />
              <span>
                Usage for pricing: <b className="text-gray-700">{usage.ai.month_calls} OpenAI calls this month ({fmtUsd(usage.ai.month_cost_usd)})</b>
                {" · "}{usage.files.uploads} uploads, {fmtBytes(usage.files.bytes)} stored
                {usage.database && <> · {fmtBytes(usage.database.bytes)} of database</>}
              </span>
            </div>
          )}
          <table className="w-full">
            <thead>
              <tr className="text-[10px] uppercase tracking-wide text-gray-400 text-left">
                <th className="pb-1 font-semibold">Description</th>
                <th className="pb-1 font-semibold w-20">SAC</th>
                <th className="pb-1 font-semibold w-16">Qty</th>
                <th className="pb-1 font-semibold w-28">Rate (₹)</th>
                <th className="pb-1 font-semibold w-28 text-right">Amount</th>
                <th className="w-7" />
              </tr>
            </thead>
            <tbody>
              {form.lines.map((l, i) => (
                <tr key={i} className="align-top">
                  <td className="pr-2 pb-2">
                    <input className={CELL} value={l.description} onChange={(e) => setLine(i, { description: e.target.value })}
                      placeholder="e.g. Fareqube subscription — September 2026" />
                  </td>
                  <td className="pr-2 pb-2"><input className={CELL} value={l.sac ?? ""} onChange={(e) => setLine(i, { sac: e.target.value })} /></td>
                  <td className="pr-2 pb-2"><input className={CELL} inputMode="decimal" value={l.quantity} onChange={(e) => setLine(i, { quantity: e.target.value })} /></td>
                  <td className="pr-2 pb-2"><input className={CELL} inputMode="decimal" value={l.unit_price} onChange={(e) => setLine(i, { unit_price: e.target.value })} /></td>
                  <td className="pb-2 pt-1.5 text-right text-xs tabular-nums text-gray-700">{rupees(lineAmount(l), 2)}</td>
                  <td className="pb-2 pl-1 pt-1">
                    <button
                      onClick={() => set("lines", form.lines.filter((_, j) => j !== i))}
                      disabled={form.lines.length === 1}
                      title="Remove line"
                      className="p-1 rounded text-gray-300 hover:text-red-500 hover:bg-red-50 disabled:opacity-0"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-[10px] text-gray-400">A negative rate makes a discount line.</p>

          {/* Tax and totals */}
          <div className="flex gap-6 items-start">
            <div className="flex-1 space-y-2">
              <Field label="GST rate">
                <select className={`${INPUT} w-32`} value={form.gst_rate} onChange={(e) => set("gst_rate", Number(e.target.value))}>
                  {GST_RATES.map((r) => <option key={r} value={r}>{r}%</option>)}
                </select>
              </Field>
              <p className={`text-[11px] ${totals.blocked ? "text-amber-600" : "text-gray-500"}`}>{totals.note}</p>
            </div>
            <div className="w-60 text-xs rounded-lg border border-gray-100 divide-y divide-gray-100">
              <div className="flex justify-between px-3 py-1.5"><span className="text-gray-500">Subtotal</span><span className="tabular-nums">{rupees(totals.subtotal, 2)}</span></div>
              {totals.cgst > 0 && <div className="flex justify-between px-3 py-1.5"><span className="text-gray-500">CGST {form.gst_rate / 2}%</span><span className="tabular-nums">{rupees(totals.cgst, 2)}</span></div>}
              {totals.sgst > 0 && <div className="flex justify-between px-3 py-1.5"><span className="text-gray-500">SGST {form.gst_rate / 2}%</span><span className="tabular-nums">{rupees(totals.sgst, 2)}</span></div>}
              {totals.igst > 0 && <div className="flex justify-between px-3 py-1.5"><span className="text-gray-500">IGST {form.gst_rate}%</span><span className="tabular-nums">{rupees(totals.igst, 2)}</span></div>}
              <div className="flex justify-between px-3 py-2 font-bold text-gray-900 bg-gray-50 rounded-b-lg"><span>Total</span><span className="tabular-nums">{rupees(totals.total, 2)}</span></div>
            </div>
          </div>
        </Section>

        {/* The platform's own details — the same on every invoice, remembered from the last one. */}
        <section className="rounded-lg border border-gray-100">
          <button
            onClick={() => setShowIssuer(!showIssuer)}
            className="w-full flex items-center gap-2 px-3 py-2.5 text-left hover:bg-gray-50 rounded-lg"
          >
            {showIssuer ? <ChevronDown className="w-3.5 h-3.5 text-gray-400" /> : <ChevronRight className="w-3.5 h-3.5 text-gray-400" />}
            <Building2 className="w-3.5 h-3.5 text-gray-400" />
            <span className="text-xs font-bold text-gray-800">Your company &amp; bank details</span>
            {!showIssuer && <span className="text-[11px] text-gray-400 truncate">{issuerSummary}</span>}
          </button>
          {showIssuer && (
            <div className="px-3 pb-3 space-y-4">
              <p className="text-[10px] text-gray-400">
                Printed as the seller on the invoice, and remembered for the next one. Without a GSTIN the
                invoice carries no GST.
              </p>
              <PartyFields value={issuer} onChange={(p) => setIssuer(p)} />
              <div className="grid grid-cols-2 gap-3">
                {([
                  ["account_name", "Account name"], ["account_number", "Account number"], ["ifsc", "IFSC"],
                  ["bank_name", "Bank"], ["branch", "Branch"], ["upi_id", "UPI ID"],
                ] as const).map(([k, label]) => (
                  <Field key={k} label={label}>
                    <input className={INPUT} value={bank[k] ?? ""} onChange={(e) => setIssuer({ bank: { ...bank, [k]: e.target.value } })} />
                  </Field>
                ))}
              </div>
            </div>
          )}
        </section>

        <Field label="Notes (printed on the invoice)">
          <textarea className={INPUT} rows={2} value={form.notes ?? ""} onChange={(e) => set("notes", e.target.value)}
            placeholder="e.g. Thank you for your business." />
        </Field>

        {(error || problem) && <p className={`text-[11px] ${error ? "text-red-500" : "text-amber-600"}`}>{error || problem}</p>}

        <div className="flex gap-2 pt-1 sticky bottom-0 bg-white pb-1">
          <button onClick={onClose} className="flex-1 border border-gray-200 text-gray-600 rounded-lg py-2 text-sm font-medium hover:bg-gray-50">
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={saving || !!problem}
            className="flex-1 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50"
            style={{ background: "linear-gradient(135deg, #7c3aed, #6d28d9)" }}
          >
            {saving ? "Generating…" : `Generate invoice · ${rupees(totals.total, 2)}`}
          </button>
        </div>
      </div>
    </ModalShell>
  );
}
