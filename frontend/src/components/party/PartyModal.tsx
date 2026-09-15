"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { X } from "lucide-react";
import api from "@/lib/api";
import {
  CORPORATE_TYPES, GSTIN_RE, INHERITED_FIELDS, MARKUP_CATEGORIES, PAN_RE, PARTY,
  corporateLabel, seedFromCorporate,
  type CategoryMarkups, type InheritedField, type InheritedValues, type MarkupCategory,
  type MarkupType, type Party, type PartyKind,
} from "@/lib/party";
import { PARTY_ICON } from "@/components/party/icons";
import { STATE_NAMES } from "@/lib/indiaTax";

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
 * One row of the category table AS TYPED. A row is filled in two steps — type, then
 * value — so its half-way state has to survive a render. It used to be written straight
 * into `form.category_markups`, which only accepts finished rows, so picking a type
 * deleted the row again and no category could ever be set.
 *
 * `form.category_markups` still only ever holds FINISHED rows: that is what inheritance
 * compares and what gets saved. These drafts are the screen's copy.
 */
type CategoryRow = { type: MarkupType | ""; value: string };
type CategoryRows = Record<MarkupCategory, CategoryRow>;

function toCategoryRows(markups: CategoryMarkups | null | undefined): CategoryRows {
  return Object.fromEntries(
    MARKUP_CATEGORIES.map(({ value }) => {
      const entry = markups?.[value];
      return [value, { type: entry?.type ?? "", value: entry?.value != null ? String(entry.value) : "" }];
    }),
  ) as CategoryRows;
}

/** Finished rows only. A type with no number is not a markup yet — handleSave reports it. */
function fromCategoryRows(rows: CategoryRows): CategoryMarkups {
  const out: CategoryMarkups = {};
  for (const { value: slug } of MARKUP_CATEGORIES) {
    const { type, value } = rows[slug];
    const num = value.trim() === "" ? NaN : Number(value);
    if (type && !Number.isNaN(num)) out[slug] = { type, value: num };
  }
  return out;
}

/**
 * A field label, marked when the value below it was copied from a corporate
 * rather than typed. The mark is generic and the employer's name lives in the
 * tooltip — a long company name in eight labels wraps the whole form.
 */
function FieldLabel({ text, from }: { text: string; from?: string }) {
  return (
    <label className={LABEL}>
      {text}
      {from && (
        <span
          className="ml-1.5 font-medium normal-case tracking-normal text-[10px] text-blue-500"
          title={`Filled in from ${from}`}
        >
          · inherited
        </span>
      )}
    </label>
  );
}

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
    // A NEW corporate starts Registered, since most are; a new employee starts
    // Unregistered. An existing party keeps what it has.
    gst_registered: party?.gst_registered || (!isEdit && isCorporate) ? "true" : "false",
    gst_no: party?.gst_no ?? "",
    pan_no: party?.pan_no ?? "",
    markup_type: party?.markup_type ?? "",
    markup_value: party?.markup_value != null ? String(party.markup_value) : "",
    // The one non-string field on this form. Cloned so editing a cell cannot reach back
    // into the loaded party object the list is still rendering from.
    category_markups: (party?.category_markups
      ? structuredClone(party.category_markups)
      : {}) as CategoryMarkups,
    employee_code: party?.employee_code ?? "",
    // Agency on a NEW party, the way `country` defaults to India above. Blank is
    // not a neutral starting point here: billing_calc.compute_gst applies NO GST
    // at all to an unset billing type, so a party onboarded without touching this
    // field would be invoiced tax-free and nothing on the screen would say so.
    // An existing party keeps whatever it has, including blank — this fixes the
    // default, it does not retag anyone.
    billing_type: party?.billing_type ?? (isEdit ? "" : "agency"),
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  // A NEW party's "agency" above is the form's placeholder, not a choice anyone made — so
  // an employer's billing type must replace it. Without this, an employee added under a
  // Reseller corporate was saved as Agency and taxed on the service charge alone. It stops
  // being a placeholder the moment the user picks a billing type themselves.
  const [billingIsDefault, setBillingIsDefault] = useState(!isEdit);

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

  // Fields currently holding a value copied from the selected corporate. A field
  // leaves this set the moment the user types in it, which is what stops a later
  // change of employer from overwriting something they entered by hand.
  const [inherited, setInherited] = useState<Set<string>>(new Set());
  const selectedCorporate = corporates.find((c) => `corp:${c.id}` === employer) ?? null;
  /** The corporate a field's current value came from, or undefined if it is the user's own. */
  const inheritedFrom = (key: InheritedField) =>
    inherited.has(key) && selectedCorporate ? corporateLabel(selectedCorporate) : undefined;

  const set = (k: keyof typeof form, v: string | CategoryMarkups) => {
    setForm((p) => ({ ...p, [k]: v }));
    if (k === "billing_type") setBillingIsDefault(false);
    setInherited((prev) => {
      if (!prev.has(k)) return prev;
      const next = new Set(prev);
      next.delete(k);
      return next;
    });
  };

  const categoryCount = Object.keys(form.category_markups).length;
  const [categoryRows, setCategoryRows] = useState<CategoryRows>(
    () => toCategoryRows(party?.category_markups),
  );

  // Does the chosen employer already have someone by this name? A WARNING, never a block:
  // the server's register is the rule (services/party_dedupe) and it will 409 if this is a
  // real clash. This just puts the fix — an Employee Code — in front of the user before
  // they hit Save, rather than after.
  const [nameTwin, setNameTwin] = useState<string | null>(null);
  useEffect(() => {
    const first = form.first_name.trim();
    if (isCorporate || !first || form.employee_code.trim()) { setNameTwin(null); return; }
    const corporateId = employer.startsWith("corp:") ? Number(employer.slice(5)) : null;
    let cancelled = false;
    const t = setTimeout(async () => {
      try {
        const { data } = await api.get<Party[]>("/customers/", {
          params: { search: first, limit: 50 },
        });
        if (cancelled) return;
        const wanted = `${first} ${form.last_name.trim()}`.trim().toLowerCase();
        const twin = data.find(
          (c) =>
            c.id !== party?.id &&
            (c.corporate_id ?? null) === corporateId &&
            `${c.first_name ?? ""} ${c.last_name ?? ""}`.trim().toLowerCase() === wanted,
        );
        setNameTwin(twin ? (twin.company || "This workspace") : null);
      } catch {
        // A failed lookup must never stand between the user and Save.
      }
    }, 400);
    return () => { cancelled = true; clearTimeout(t); };
  }, [form.first_name, form.last_name, form.employee_code, employer, isCorporate, party?.id]);

  /**
   * One cell of the category table. The draft keeps whatever was typed; only finished rows
   * reach `form.category_markups`, because a type with no value, or a value with no type,
   * bills nothing (billing_calc.compute_markup is inert on both). Setting the type back to
   * Default is how you return a category to the party's default rate.
   */
  const editCategory = (category: MarkupCategory, patch: Partial<CategoryRow>) => {
    const row = { ...categoryRows[category], ...patch };
    // Typing a number into a Default row starts an override quoted the way the default is.
    if (patch.value !== undefined && patch.value.trim() !== "" && !row.type) {
      row.type = form.markup_type === "fixed" ? "fixed" : "percentage";
    }
    if (!row.type) row.value = "";
    const rows = { ...categoryRows, [category]: row };
    setCategoryRows(rows);
    set("category_markups", fromCategoryRows(rows));
  };

  /** What a Default row bills at, shown in its empty value box. */
  const defaultMarkupHint =
    form.markup_type && form.markup_value.trim()
      ? `Default ${form.markup_type === "fixed" ? `₹${form.markup_value}` : `${form.markup_value}%`}`
      : "Default";

  /** Switching employer re-seeds the inherited fields — see seedFromCorporate. */
  const selectEmployer = (next: string) => {
    setEmployer(next);
    const corporate = corporates.find((c) => `corp:${c.id}` === next) ?? null;
    const current = Object.fromEntries(
      INHERITED_FIELDS.map((k) => [k, form[k]])
    ) as InheritedValues;
    // The placeholder billing type is offered up for replacement like a held value.
    const replaceable = billingIsDefault ? new Set([...inherited, "billing_type"]) : inherited;
    const seeded = seedFromCorporate(current, replaceable, corporate);
    if (billingIsDefault && !seeded.values.billing_type) {
      // The employer has no billing type (or there is no employer): keep the safe default,
      // and do not mark it as coming from the corporate.
      seeded.values.billing_type = "agency";
      seeded.held.delete("billing_type");
    }
    setForm((prev) => ({ ...prev, ...seeded.values }));
    setInherited(seeded.held as Set<string>);
    // Re-seeding hands back the same object when it left the categories alone.
    if (seeded.values.category_markups !== current.category_markups) {
      setCategoryRows(toCategoryRows(seeded.values.category_markups));
    }
  };

  // A corporate is identified by its name; a customer by the person's first name.
  const requiredValue = isCorporate ? form.company : form.first_name;

  const handleSave = async () => {
    if (!requiredValue.trim()) {
      setError(isCorporate ? "Corporate name is required." : "First name is required.");
      return;
    }
    // Place of supply falls back to the state whenever there is no GSTIN, so a corporate
    // without one would bill GST that cannot be split into CGST + SGST or IGST.
    if (isCorporate && !form.state.trim()) {
      setError("State is required. It decides whether this corporate's invoices carry CGST + SGST or IGST.");
      return;
    }
    if (form.markup_value && isNaN(Number(form.markup_value))) {
      setError("Markup value must be a number.");
      return;
    }
    const unfinished = MARKUP_CATEGORIES.filter(({ value }) => {
      const row = categoryRows[value];
      return row.type && (row.value.trim() === "" || Number.isNaN(Number(row.value)));
    });
    if (unfinished.length) {
      setError(
        `Enter a markup value for ${unfinished.map((c) => c.label).join(", ")}, or set it back to Default.`
      );
      return;
    }
    const registered = form.gst_registered === "true";
    const gstNo = form.gst_no.trim().toUpperCase();
    const panNo = form.pan_no.trim().toUpperCase();
    if (registered && !GSTIN_RE.test(gstNo)) {
      setError(
        `A valid 15-character GST No is required for a registered ${cfg.masterSingular.toLowerCase()} ` +
        "(e.g. 27ABCDE1234F1Z5). If they have none, choose Unregistered."
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
      // null, not {}, so the column stays NULL — the server treats the two as one
      // state and this keeps the wire honest about which it is.
      category_markups: categoryCount ? form.category_markups : null,
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
          employee_code: form.employee_code.trim().toUpperCase() || null,
          title: form.title.trim() || null,
          // The only geographic field `customers` has, and it exists for place
          // of supply on a direct bill. Cleared when they have a GSTIN, which
          // already says which state they are registered in.
          state: registered ? null : (form.state.trim() || null),
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

              <div>
                <label className={LABEL}>Employee Code</label>
                <input
                  value={form.employee_code}
                  onChange={(e) => set("employee_code", e.target.value.toUpperCase())}
                  placeholder="e.g. EMP-042 (optional)"
                  maxLength={50}
                  className={INPUT}
                />
                {/* The only field that can tell two people of one name apart: every other
                    detail on this form is either the name itself or inherited from their
                    corporate, so colleagues legitimately share it. */}
                {nameTwin ? (
                  <p className="text-[10px] text-amber-600 mt-1">
                    <strong>{nameTwin}</strong> already has someone by this name. Give this
                    one an Employee Code so bills and pickers can tell them apart.
                  </p>
                ) : (
                  <p className="text-[10px] text-gray-400 mt-1">
                    Your own reference for this person. Needed only when two of them share a name.
                  </p>
                )}
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className={LABEL}>Company</label>
                  <select
                    value={employer}
                    onChange={(e) => selectEmployer(e.target.value)}
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

              {inherited.size > 0 && selectedCorporate && (
                <p className="text-[11px] text-blue-700 bg-blue-50 border border-blue-200 rounded-lg px-3 py-2 -mt-1">
                  Filled in from{" "}
                  <span className="font-semibold">{corporateLabel(selectedCorporate)}</span> — change any of
                  it below and this employee keeps your version.
                </p>
              )}
            </>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div>
              <FieldLabel text="Phone / Contact" from={inheritedFrom("phone")} />
              <input value={form.phone} onChange={(e) => set("phone", e.target.value)} placeholder="+91-XXXXXXXXXX" className={INPUT} />
            </div>
            <div>
              <FieldLabel text="Email" from={inheritedFrom("email")} />
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
                  {/* Required, and a picker rather than free text: place of supply matches
                      the state to a GSTIN state code, so a spelling it cannot read is as
                      good as no state — and for an Unregistered corporate the state is the
                      only thing it has to go on. */}
                  <label className={LABEL}>State *</label>
                  <select value={form.state} onChange={(e) => set("state", e.target.value)} className={INPUT}>
                    <option value="">— Select state —</option>
                    {/* A spelling stored before this was a picker would otherwise vanish. */}
                    {form.state && !STATE_NAMES.includes(form.state) && (
                      <option value={form.state}>{form.state}</option>
                    )}
                    {STATE_NAMES.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
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

            </>
          )}

          <p className={SECTION}>Billing &amp; Tax</p>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <FieldLabel text="Default Markup Type" from={inheritedFrom("markup_type")} />
              <select value={form.markup_type} onChange={(e) => set("markup_type", e.target.value)} className={INPUT}>
                <option value="">— Select —</option>
                <option value="percentage">Percentage (%)</option>
                <option value="fixed">Fixed (₹)</option>
              </select>
            </div>
            <div>
              <FieldLabel
                text={`Default Markup Value ${form.markup_type === "percentage" ? "(%)" : form.markup_type === "fixed" ? "(₹)" : ""}`.trim()}
                from={inheritedFrom("markup_value")}
              />
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
            <FieldLabel
              text={`Markup by category${categoryCount ? ` · ${categoryCount} set` : ""}`}
              from={inheritedFrom("category_markups")}
            />
            <div className="rounded-lg border border-gray-200 divide-y divide-gray-100">
              {MARKUP_CATEGORIES.map(({ value, label }) => {
                const row = categoryRows[value];
                return (
                  <div key={value} className="grid grid-cols-[4.5rem_1fr_1fr] gap-2 items-center px-2.5 py-1.5">
                    <span className="text-xs font-medium text-gray-600">{label}</span>
                    <select
                      value={row.type}
                      onChange={(e) => editCategory(value, { type: e.target.value as MarkupType | "" })}
                      className={INPUT + " py-1 text-xs"}
                    >
                      {/* How you CLEAR an override — the top-level select has no such option. */}
                      <option value="">Default</option>
                      <option value="percentage">Percentage (%)</option>
                      <option value="fixed">Fixed (₹)</option>
                    </select>
                    <input
                      type="number"
                      step="any"
                      value={row.value}
                      onChange={(e) => editCategory(value, { value: e.target.value })}
                      placeholder={row.type === "fixed" ? "e.g. 500" : row.type ? "e.g. 5" : defaultMarkupHint}
                      className={INPUT + " py-1 text-xs"}
                    />
                  </div>
                );
              })}
            </div>
            <p className="text-[10px] text-gray-400 mt-1">
              A category left on Default uses the default markup above. Air rates apply to
              ticket billing today; Hotel, Train, Bus, Car and MICE are saved now and apply
              to those bills as they come online.
            </p>
          </div>

          <div>
            <FieldLabel text="Billing Type" from={inheritedFrom("billing_type")} />
            <select value={form.billing_type} onChange={(e) => set("billing_type", e.target.value)} className={INPUT}>
              {/* Only offered while it IS blank — an existing party may predate the
                  Agency default, and hiding its current value would silently change
                  it on the next save. New parties never see it. */}
              {!form.billing_type && <option value="">— Select —</option>}
              <option value="agency">Agency</option>
              <option value="reseller">Reseller</option>
            </select>
            <p className="text-[10px] text-gray-400 mt-1">
              {form.billing_type === "reseller"
                ? "GST on the whole sale — fare, taxes and service charge."
                : form.billing_type === "agency"
                  ? "GST on your service charge only. The fare and taxes are not taxed again."
                  : "No billing type means no GST is charged. Pick one."}
            </p>
          </div>

          {/* Registered / Unregistered for BOTH kinds. A GST No is asked for, and
              required, only when Registered — some corporates genuinely have none,
              and then the State decides CGST + SGST vs IGST instead. */}
          <div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <FieldLabel text="GST Registration" from={inheritedFrom("gst_registered")} />
                <select
                  value={form.gst_registered}
                  onChange={(e) => {
                    set("gst_registered", e.target.value);
                    if (e.target.value === "false") set("gst_no", "");
                  }}
                  className={INPUT}
                >
                  <option value="true">Registered</option>
                  <option value="false">Unregistered</option>
                </select>
              </div>
              {form.gst_registered === "true" && (
                <div>
                  <FieldLabel text="GST No *" from={inheritedFrom("gst_no")} />
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
            {isCorporate && (
              <p className="text-[10px] text-gray-400 mt-1">
                {form.gst_registered === "true"
                  ? "Its GSTIN decides whether this corporate's invoices carry CGST + SGST or IGST."
                  : "No GSTIN, so the State above decides whether its invoices carry CGST + SGST or IGST."}
              </p>
            )}
          </div>

          {/* A DIRECT customer's place of supply. Only consulted when they have
              no GSTIN — a GSTIN already names the state it is registered in —
              and only for a bill raised to the person rather than to their
              employer, whose own registration decides that case.
              A picker, not free text: place of supply matches a state to a GSTIN
              state code, so a spelling it cannot read is as good as no state. */}
          {!isCorporate && form.gst_registered !== "true" && (
            <div>
              {/* Not an INHERITED_FIELD, deliberately: a direct customer is billed
                  as themselves, so their employer's state is not theirs. */}
              <label className={LABEL}>State</label>
              <select value={form.state} onChange={(e) => set("state", e.target.value)} className={INPUT}>
                <option value="">— Select state —</option>
                {/* A spelling stored before this was a picker would otherwise
                    vanish on the next save. Keep it visible. */}
                {form.state && !STATE_NAMES.includes(form.state) && (
                  <option value={form.state}>{form.state}</option>
                )}
                {STATE_NAMES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <p className="text-[10px] text-gray-400 mt-1">
                Where they are, for billing them directly. Same state as yours means
                CGST + SGST; a different one means IGST. Without it the GST on their
                tickets is charged but cannot be split.
              </p>
            </div>
          )}

          <div>
            <FieldLabel text="PAN No" from={inheritedFrom("pan_no")} />
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
