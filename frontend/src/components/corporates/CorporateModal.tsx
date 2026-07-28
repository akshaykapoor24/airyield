"use client";

import { useState } from "react";
import { Building, X } from "lucide-react";
import api from "@/lib/api";

export type MarkupType = "percentage" | "fixed";
export type BillingType = "reseller" | "agency";

export type Corporate = {
  id: number;
  first_name: string;
  last_name: string | null;
  company: string | null;
  title: string | null;
  phone: string | null;
  email: string | null;
  gst_registered: boolean;
  gst_no: string | null;
  pan_no: string | null;
  markup_type: MarkupType | null;
  markup_value: number | null;
  billing_type: BillingType | null;
  is_active: boolean;
};

// Shared with ProfileInfoSection / signup: GSTIN = 15 chars, PAN = 10 chars.
const PAN_RE = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
const GSTIN_RE = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;

const LABEL = "block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1";
const INPUT =
  "w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30 bg-gray-50";

export default function CorporateModal({
  corporate,
  onClose,
  onSaved,
}: {
  corporate?: Corporate | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = !!corporate?.id;
  const [form, setForm] = useState({
    first_name: corporate?.first_name ?? "",
    last_name: corporate?.last_name ?? "",
    company: corporate?.company ?? "",
    title: corporate?.title ?? "",
    phone: corporate?.phone ?? "",
    email: corporate?.email ?? "",
    gst_registered: corporate?.gst_registered ? "true" : "false",
    gst_no: corporate?.gst_no ?? "",
    pan_no: corporate?.pan_no ?? "",
    markup_type: corporate?.markup_type ?? "",
    markup_value: corporate?.markup_value != null ? String(corporate.markup_value) : "",
    billing_type: corporate?.billing_type ?? "",
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
    const registered = form.gst_registered === "true";
    const gstNo = form.gst_no.trim().toUpperCase();
    const panNo = form.pan_no.trim().toUpperCase();
    if (registered && !GSTIN_RE.test(gstNo)) {
      setError("A valid 15-character GST No is required for registered corporates (e.g. 27ABCDE1234F1Z5).");
      return;
    }
    if (panNo && !PAN_RE.test(panNo)) {
      setError("Invalid PAN No (e.g. ABCDE1234F).");
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
      gst_registered: registered,
      gst_no: registered ? (gstNo || null) : null,
      pan_no: panNo || null,
      markup_type: form.markup_type || null,
      markup_value: form.markup_value ? Number(form.markup_value) : null,
      billing_type: form.billing_type || null,
    };
    try {
      if (isEdit) {
        await api.patch(`/corporates/${corporate!.id}`, payload);
      } else {
        await api.post("/corporates/", payload);
      }
      onSaved();
      onClose();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Failed to save corporate.");
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
              <Building className="w-4 h-4 text-[#1e3a5f]" />
            </div>
            <h2 className="text-sm font-bold text-gray-900">{isEdit ? "Edit Corporate" : "Add Corporate"}</h2>
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
              <input type="email" value={form.email} onChange={(e) => set("email", e.target.value)} placeholder="corporate@email.com" className={INPUT} />
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

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={LABEL}>GST Registration</label>
              <select
                value={form.gst_registered}
                onChange={(e) => {
                  set("gst_registered", e.target.value);
                  if (e.target.value === "false") set("gst_no", "");
                }}
                className={INPUT}
              >
                <option value="false">Unregistered</option>
                <option value="true">Registered</option>
              </select>
            </div>
            {form.gst_registered === "true" && (
              <div>
                <label className={LABEL}>GST No *</label>
                <input
                  value={form.gst_no}
                  onChange={(e) => set("gst_no", e.target.value.toUpperCase())}
                  placeholder="27ABCDE1234F1Z5"
                  maxLength={15}
                  className={`${INPUT} uppercase`}
                />
              </div>
            )}
          </div>

          <div>
            <label className={LABEL}>PAN No</label>
            <input
              value={form.pan_no}
              onChange={(e) => set("pan_no", e.target.value.toUpperCase())}
              placeholder="ABCDE1234F (optional)"
              maxLength={10}
              className={`${INPUT} uppercase`}
            />
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
            {saving ? "Saving…" : isEdit ? "Save Changes" : "Add Corporate"}
          </button>
        </div>
      </div>
    </div>
  );
}
