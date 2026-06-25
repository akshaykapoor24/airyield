"use client";

import { useState } from "react";
import { Contact, X } from "lucide-react";
import api from "@/lib/api";

export type MarkupType = "percentage" | "fixed";
export type BillingType = "reseller" | "agency";

export type Customer = {
  id: number;
  first_name: string;
  last_name: string | null;
  company: string | null;
  title: string | null;
  phone: string | null;
  email: string | null;
  gst_no: string | null;
  markup_type: MarkupType | null;
  markup_value: number | null;
  billing_type: BillingType | null;
  is_active: boolean;
};

const LABEL = "block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1";
const INPUT =
  "w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30 bg-gray-50";

export default function CustomerModal({
  customer,
  onClose,
  onSaved,
}: {
  customer?: Customer | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = !!customer?.id;
  const [form, setForm] = useState({
    first_name: customer?.first_name ?? "",
    last_name: customer?.last_name ?? "",
    company: customer?.company ?? "",
    title: customer?.title ?? "",
    phone: customer?.phone ?? "",
    email: customer?.email ?? "",
    markup_type: customer?.markup_type ?? "",
    markup_value: customer?.markup_value != null ? String(customer.markup_value) : "",
    billing_type: customer?.billing_type ?? "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const set = (k: keyof typeof form, v: string) => setForm((p) => ({ ...p, [k]: v }));

  const handleSave = async () => {
    if (!form.first_name.trim()) {
      setError("First name is required.");
      return;
    }
    if (form.markup_value && isNaN(Number(form.markup_value))) {
      setError("Markup value must be a number.");
      return;
    }
    setSaving(true);
    setError("");
    const payload = {
      first_name: form.first_name.trim(),
      last_name: form.last_name.trim() || null,
      company: form.company.trim() || null,
      title: form.title.trim() || null,
      phone: form.phone.trim() || null,
      email: form.email.trim() || null,
      markup_type: form.markup_type || null,
      markup_value: form.markup_value ? Number(form.markup_value) : null,
      billing_type: form.billing_type || null,
    };
    try {
      if (isEdit) {
        await api.patch(`/customers/${customer!.id}`, payload);
      } else {
        await api.post("/customers/", payload);
      }
      onSaved();
      onClose();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Failed to save customer.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center">
              <Contact className="w-4 h-4 text-[#1e3a5f]" />
            </div>
            <h2 className="text-sm font-bold text-gray-900">{isEdit ? "Edit Customer" : "Add Customer"}</h2>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg">
            <X className="w-4 h-4 text-gray-500" />
          </button>
        </div>

        <div className="px-6 py-4 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={LABEL}>First Name *</label>
              <input value={form.first_name} onChange={(e) => set("first_name", e.target.value)} placeholder="e.g. John" className={INPUT} />
            </div>
            <div>
              <label className={LABEL}>Last Name</label>
              <input value={form.last_name} onChange={(e) => set("last_name", e.target.value)} placeholder="e.g. Doe" className={INPUT} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={LABEL}>Company</label>
              <input value={form.company} onChange={(e) => set("company", e.target.value)} placeholder="Company name" className={INPUT} />
            </div>
            <div>
              <label className={LABEL}>Title</label>
              <input value={form.title} onChange={(e) => set("title", e.target.value)} placeholder="Mr / Ms / Director…" className={INPUT} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={LABEL}>Phone / Contact</label>
              <input value={form.phone} onChange={(e) => set("phone", e.target.value)} placeholder="+91-XXXXXXXXXX" className={INPUT} />
            </div>
            <div>
              <label className={LABEL}>Email</label>
              <input type="email" value={form.email} onChange={(e) => set("email", e.target.value)} placeholder="customer@email.com" className={INPUT} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={LABEL}>Markup Type</label>
              <select value={form.markup_type} onChange={(e) => set("markup_type", e.target.value)} className={INPUT}>
                <option value="">— Select —</option>
                <option value="percentage">Percentage (%)</option>
                <option value="fixed">Fixed (₹)</option>
              </select>
            </div>
            <div>
              <label className={LABEL}>
                Markup Value {form.markup_type === "percentage" ? "(%)" : form.markup_type === "fixed" ? "(₹)" : ""}
              </label>
              <input
                type="number"
                value={form.markup_value}
                onChange={(e) => set("markup_value", e.target.value)}
                placeholder={form.markup_type === "fixed" ? "e.g. 500" : "e.g. 10"}
                className={INPUT}
              />
            </div>
          </div>

          <div>
            <label className={LABEL}>Billing Type</label>
            <select value={form.billing_type} onChange={(e) => set("billing_type", e.target.value)} className={INPUT}>
              <option value="">— Select —</option>
              <option value="reseller">Reseller</option>
              <option value="agency">Agency</option>
            </select>
          </div>

          {error && <p className="text-[11px] text-red-500">{error}</p>}
        </div>

        <div className="px-6 pb-5 flex gap-3">
          <button onClick={onClose} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving || !form.first_name.trim()}
            className="flex-1 bg-[#1e3a5f] hover:bg-[#16304f] text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50"
          >
            {saving ? "Saving…" : isEdit ? "Save Changes" : "Add Customer"}
          </button>
        </div>
      </div>
    </div>
  );
}
