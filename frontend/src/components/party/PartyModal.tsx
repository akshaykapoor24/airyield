"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { X } from "lucide-react";
import api from "@/lib/api";
import { CORPORATE_TYPES, GSTIN_RE, PAN_RE, PARTY, corporateLabel, type Party, type PartyKind } from "@/lib/party";
import { PARTY_ICON } from "@/components/party/icons";

const LABEL = "block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1";
const INPUT =
  "w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30 bg-gray-50";
const SECTION = "text-[10px] font-bold text-gray-400 uppercase tracking-widest pt-1";

/**
 * The employer <select> has three kinds of value, and they are not interchangeable:
 *
 *   ""            individual / direct — no employer, and a real answer, not a blank
 *   "corp:<id>"   an employee of that corporate (Corporate Master)
 *   "legacy"      the free-text company an existing row was saved with before the
 *                 link existed and which matches no corporate. Offered ONLY when
 *                 editing such a row, so opening the form does not silently wipe
 *                 a value the user never touched.
 */
const INDIVIDUAL = "";
const LEGACY = "legacy";

/**
 * Add / edit form for a customer or a corporate.
 *
 * The two are NOT the same form. A customer is a person — first/last name, title,
 * and an EMPLOYER picked from Corporate Master (or none, which makes them an
 * individual / direct customer). A corporate is an organisation: it leads with
 * its legal form, its `company` IS its name, and it has a registered address.
 * Everything below the identity block (markup, billing type, GST, PAN) is shared.
 *
 * Rendered only from PartyDirectory in MASTER mode, so its wording comes from
 * cfg.masterSingular / masterPlural — "Add Employee", not "Add Customer".
 */
export default function PartyModal({
  kind,
  party,
  onClose,
  onSaved,
}: {
  kind: PartyKind;
  party?: Party | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const cfg = PARTY[kind];
  const Icon = PARTY_ICON[kind];
  const isEdit = !!party?.id;
  const isCorporate = kind === "corporate";
  const [form, setForm] = useState({
    first_name: party?.first_name ?? "",
    last_name: party?.last_name ?? "",
    company: party?.company ?? "",
    title: party?.title ?? "",
    corporate_type: party?.corporate_type ?? "",
    address: party?.address ?? "",
    city: party?.city ?? "",
    state: party?.state ?? "",
    pincode: party?.pincode ?? "",
    country: party?.country ?? (isEdit ? "" : "India"),
    phone: party?.phone ?? "",
    email: party?.email ?? "",
    gst_registered: party?.gst_registered ? "true" : "false",
    gst_no: party?.gst_no ?? "",
    pan_no: party?.pan_no ?? "",
    markup_type: party?.markup_type ?? "",
    markup_value: party?.markup_value != null ? String(party.markup_value) : "",
    billing_type: party?.billing_type ?? "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  // Employer picker (customers only). A row with a company but no corporate_id
  // predates the link, so its text is offered back as its own option.
  const hasLegacyCompany = !isCorporate && !!party?.company && party?.corporate_id == null;
  const [corporates, setCorporates] = useState<Party[]>([]);
  const [corporatesLoaded, setCorporatesLoaded] = useState(false);
  const [employer, setEmployer] = useState<string>(
    party?.corporate_id != null ? `corp:${party.corporate_id}` : hasLegacyCompany ? LEGACY : INDIVIDUAL
  );

  useEffect(() => {
    if (isCorporate) return;
    let cancelled = false;
    (async () => {
      try {
        const { data } = await api.get<Party[]>("/corporates/", { params: { limit: 1000 } });
        if (!cancelled) setCorporates(data.filter((c) => c.is_active));
      } catch {
        // A failed load must not block saving — the picker just offers
        // Individual / Direct, which is the safe answer.
      } finally {
        if (!cancelled) setCorporatesLoaded(true);
      }
    })();
    return () => { cancelled = true; };
  }, [isCorporate]);

  const set = (k: keyof typeof form, v: string) => setForm((p) => ({ ...p, [k]: v }));

  // A corporate is identified by its name; a customer by the person's first name.
  const requiredValue = isCorporate ? form.company : form.first_name;

  const handleSave = async () => {
    if (!requiredValue.trim()) {
      setError(isCorporate ? "Corporate name is required." : "First name is required.");
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
      setError(
        `A valid 15-character GST No is required for registered ${cfg.masterPlural.toLowerCase()} (e.g. 27ABCDE1234F1Z5).`
      );
      return;
    }
    if (panNo && !PAN_RE.test(panNo)) {
      setError("Invalid PAN No (e.g. ABCDE1234F).");
      return;
    }
    setSaving(true);
    setError("");
    const shared = {
      company: form.company.trim() || null,
      phone: form.phone.trim() || null,
      email: form.email.trim() || null,
      gst_registered: registered,
      gst_no: registered ? (gstNo || null) : null,
      pan_no: panNo || null,
      markup_type: form.markup_type || null,
      markup_value: form.markup_value ? Number(form.markup_value) : null,
      billing_type: form.billing_type || null,
    };
    // The two routers take different payloads: /corporates/ has no person
    // columns to write to, and /customers/ has no address columns.
    const payload = isCorporate
      ? {
          ...shared,
          company: form.company.trim(),
          corporate_type: form.corporate_type || null,
          address: form.address.trim() || null,
          city: form.city.trim() || null,
          state: form.state.trim() || null,
          pincode: form.pincode.trim() || null,
          country: form.country.trim() || null,
        }
      : {
          ...shared,
          first_name: form.first_name.trim(),
          last_name: form.last_name.trim() || null,
          title: form.title.trim() || null,
          // The backend derives `company` from corporate_id whenever one is set,
          // so the only company text worth sending is a kept legacy value.
          corporate_id: employer.startsWith("corp:") ? Number(employer.slice(5)) : null,
          company: employer === LEGACY ? (party?.company ?? null) : null,
        };
    try {
      if (isEdit) {
        await api.patch(`/${cfg.resource}/${party!.id}`, payload);
      } else {
        await api.post(`/${cfg.resource}/`, payload);
      }
      onSaved();
      onClose();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? `Failed to save ${cfg.masterSingular.toLowerCase()}.`);
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
              <Icon className="w-4 h-4 text-[#1e3a5f]" />
            </div>
            <h2 className="text-sm font-bold text-gray-900">
              {isEdit ? `Edit ${cfg.masterSingular}` : `Add ${cfg.masterSingular}`}
            </h2>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg">
            <X className="w-4 h-4 text-gray-500" />
          </button>
        </div>

        <div className="px-6 py-4 space-y-3">
          {isCorporate ? (
            <>
              <div>
                <label className={LABEL}>Corporate Type</label>
                <select
                  value={form.corporate_type}
                  onChange={(e) => set("corporate_type", e.target.value)}
                  className={INPUT}
                >
                  <option value="">— Select —</option>
                  {CORPORATE_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className={LABEL}>Corporate Name *</label>
                <input
                  value={form.company}
                  onChange={(e) => set("company", e.target.value)}
                  placeholder="e.g. Acme Pvt Ltd"
                  className={INPUT}
                />
              </div>
            </>
          ) : (
            <>
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
                  <select
                    value={employer}
                    onChange={(e) => setEmployer(e.target.value)}
                    className={INPUT}
                    disabled={!corporatesLoaded}
                  >
                    <option value={INDIVIDUAL}>Individual / Direct</option>
                    {corporates.map((c) => (
                      <option key={c.id} value={`corp:${c.id}`}>{corporateLabel(c)}</option>
                    ))}
                    {hasLegacyCompany && (
                      <option value={LEGACY}>{party!.company} (not linked)</option>
                    )}
                  </select>
                </div>
                <div>
                  <label className={LABEL}>Title</label>
                  <input value={form.title} onChange={(e) => set("title", e.target.value)} placeholder="Mr / Ms / Director…" className={INPUT} />
                </div>
              </div>

              {corporatesLoaded && corporates.length === 0 && (
                <p className="text-[11px] text-gray-400 -mt-1">
                  No corporates on file — this person will be saved as individual / direct. Add one in{" "}
                  <Link href={PARTY.corporate.masterHref} className="font-semibold text-[#1e3a5f] underline">
                    Corporate Master
                  </Link>
                  .
                </p>
              )}
            </>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={LABEL}>Phone / Contact</label>
              <input value={form.phone} onChange={(e) => set("phone", e.target.value)} placeholder="+91-XXXXXXXXXX" className={INPUT} />
            </div>
            <div>
              <label className={LABEL}>Email</label>
              <input type="email" value={form.email} onChange={(e) => set("email", e.target.value)} placeholder={cfg.emailPlaceholder} className={INPUT} />
            </div>
          </div>

          {isCorporate && (
            <>
              <p className={SECTION}>Registered Address</p>

              <div>
                <label className={LABEL}>Address</label>
                <textarea
                  value={form.address}
                  onChange={(e) => set("address", e.target.value)}
                  placeholder="Building, street, area"
                  rows={2}
                  className={`${INPUT} resize-none`}
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className={LABEL}>City</label>
                  <input value={form.city} onChange={(e) => set("city", e.target.value)} placeholder="e.g. Mumbai" className={INPUT} />
                </div>
                <div>
                  <label className={LABEL}>State</label>
                  <input value={form.state} onChange={(e) => set("state", e.target.value)} placeholder="e.g. Maharashtra" className={INPUT} />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className={LABEL}>Pincode</label>
                  <input
                    value={form.pincode}
                    onChange={(e) => set("pincode", e.target.value)}
                    placeholder="400069"
                    maxLength={10}
                    className={INPUT}
                  />
                </div>
                <div>
                  <label className={LABEL}>Country</label>
                  <input value={form.country} onChange={(e) => set("country", e.target.value)} placeholder="India" className={INPUT} />
                </div>
              </div>

              <p className={SECTION}>Billing &amp; Tax</p>
            </>
          )}

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
            disabled={saving || !requiredValue.trim()}
            className="flex-1 bg-[#1e3a5f] hover:bg-[#16304f] text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50"
          >
            {saving ? "Saving…" : isEdit ? "Save Changes" : `Add ${cfg.masterSingular}`}
          </button>
        </div>
      </div>
    </div>
  );
}
