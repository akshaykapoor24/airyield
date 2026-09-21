"use client";

// User information form (My Profile + onboarding step 1). Bound to
// GET/PATCH /users/me/profile. Email and account type are read-only; full name,
// company, registered address, PAN and GST are editable. Exposes save() so the
// onboarding wizard can persist on "Next".
//
// The company logo is deliberately NOT part of save(): it is a file, uploaded as
// multipart to /users/me/profile/logo, so it commits the moment it is picked and
// reports its own success. Bundling it into the JSON PATCH would mean holding an
// image in memory until an unrelated button is pressed.
//
// LAID OUT BY CONTAINER, NOT VIEWPORT. The same form renders full-width on My Profile and
// inside the onboarding wizard's modal, so the grids use container queries (`@container`,
// `@xl:` / `@4xl:`): a wide page gets the two-column settings layout, the modal gets the
// stacked one, without either knowing about the other.
//
// THE GST CALCULATION IS A POPUP (GstSchemeDialog). The scheme is picked right here, from
// two cards; the worked example — sample inputs and two result grids per rule — opens on
// request instead of sitting open under the field.

import { useState, useEffect, useRef, forwardRef, useImperativeHandle, useCallback } from "react";
import {
  RefreshCw, CheckCircle2, ImageIcon, Upload, Trash2, User, Building2, MapPin,
  Receipt, Lock, Calculator, Check, AlertTriangle, RotateCcw,
} from "lucide-react";
import api from "@/lib/api";
import { INPUT, LABEL, apiError } from "@/components/userMaster/shared";
import GstSchemeDialog, { SCHEME_SUMMARY } from "@/components/profile/GstSchemeDialog";
import ManagedByAdminNote from "@/components/profile/ManagedByAdminNote";
import { getUser } from "@/lib/auth";
import { canManageWorkspace } from "@/lib/rbac";
import { refreshCompanyLogo } from "@/lib/companyLogo";
import { SCHEMES } from "@/lib/gstSchemes";

const PAN_RE = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
const GSTIN_RE = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;

// Mirrors MAX_LOGO_BYTES in backend/app/api/v1/users.py. Checked here as well so
// an oversized pick is refused instantly instead of after the upload.
const MAX_LOGO_BYTES = 2 * 1024 * 1024;
const LOGO_TYPES = ["image/png", "image/jpeg", "image/webp"];

// A locked section's fields: a disabled <fieldset> stops every control inside it natively
// (keyboard too), and these make the boxes LOOK read-only as well as be it.
const LOCKED =
  "[&_input]:bg-gray-50 [&_input]:text-gray-500 [&_input]:cursor-not-allowed " +
  "[&_textarea]:bg-gray-50 [&_textarea]:text-gray-500 [&_textarea]:cursor-not-allowed";

const READONLY =
  "w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-gray-50 text-gray-500 cursor-not-allowed focus:outline-none";

export type Profile = {
  id: number;
  email: string;
  full_name: string;
  role: string;
  tenant_type: "corporate" | "individual" | null;
  is_verified: boolean;
  onboarding_complete: boolean;
  company_name: string | null;
  pan_number: string | null;
  gst_number: string | null;
  gst_scheme: string | null;
  address: string | null;
  city: string | null;
  state: string | null;
  pincode: string | null;
  country: string | null;
  /** The business's line, printed in the invoice letterhead — not the user's. */
  phone: string | null;
  has_logo: boolean;
  logo_name: string | null;
  logo_mime: string | null;
  logo_size: number | null;
};

export type ProfileInfoHandle = { save: () => Promise<boolean> };

type Props = {
  hideSaveButton?: boolean;
  onSaved?: () => void;
  /** Offer the "How GST is calculated" popup beside the scheme choice.
   *
   *  Off in the onboarding wizard: a tax calculator is a lot to meet before you have
   *  typed your company name. The scheme choice itself stays — electing one is workspace
   *  setup exactly like PAN and GSTIN, which step 1 already collects.
   *
   *  Deliberately NOT keyed off `hideSaveButton`. That prop means one thing — "the
   *  wizard's Next button saves, so hide mine" — and overloading it would make the next
   *  edit here ambiguous. */
  showGstCalculator?: boolean;
  /** Told whenever the stored profile changes — loaded, saved, logo replaced — so the
   *  page header can show the same name, company and logo without fetching twice. */
  onProfileChange?: (profile: Profile) => void;
};

type Form = {
  full_name: string; company_name: string; pan_number: string; gst_number: string; gst_scheme: string;
  address: string; city: string; state: string; pincode: string; country: string; phone: string;
};

const toForm = (p: Profile): Form => ({
  full_name: p.full_name ?? "",
  company_name: p.company_name ?? "",
  pan_number: p.pan_number ?? "",
  gst_number: p.gst_number ?? "",
  gst_scheme: p.gst_scheme ?? "",
  address: p.address ?? "",
  city: p.city ?? "",
  state: p.state ?? "",
  pincode: p.pincode ?? "",
  country: p.country ?? "",
  phone: p.phone ?? "",
});

const EMPTY_FORM: Form = {
  full_name: "", company_name: "", pan_number: "", gst_number: "", gst_scheme: "",
  address: "", city: "", state: "", pincode: "", country: "", phone: "",
};

function fileSize(bytes: number | null): string {
  if (!bytes) return "";
  return bytes < 1024 * 1024 ? `${Math.round(bytes / 1024)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** One titled block of the form. On a wide container the title sits in a left column
 *  beside the fields (the usual settings-page layout); narrower, it stacks above them. */
function Section({ icon: Icon, title, description, locked = false, children }: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description: string;
  /** Read-only for this viewer: every field inside is disabled. */
  locked?: boolean;
  children: React.ReactNode;
}) {
  return (
    <section className="grid gap-4 @4xl:grid-cols-[240px_1fr] @4xl:gap-8 py-6 first:pt-0 border-b border-gray-100 last:border-b-0">
      <div className="flex items-start gap-3">
        <span className="w-8 h-8 rounded-lg bg-[#1e4d8c]/8 text-[#1e4d8c] flex items-center justify-center shrink-0">
          <Icon className="w-4 h-4" />
        </span>
        <div>
          <h3 className="text-[13px] font-bold text-gray-900">{title}</h3>
          <p className="text-[11px] text-gray-500 mt-0.5 leading-relaxed">{description}</p>
        </div>
      </div>
      <fieldset disabled={locked} className={`space-y-4 min-w-0 ${locked ? LOCKED : ""}`}>{children}</fieldset>
    </section>
  );
}

function Field({ label, hint, error, children, className = "" }: {
  label: string; hint?: React.ReactNode; error?: string; children: React.ReactNode; className?: string;
}) {
  return (
    <div className={className}>
      <label className={LABEL}>{label}</label>
      {children}
      {error
        ? <p className="text-[10px] text-red-500 mt-1">{error}</p>
        : hint ? <p className="text-[10px] text-gray-400 mt-1">{hint}</p> : null}
    </div>
  );
}

const ProfileInfoSection = forwardRef<ProfileInfoHandle, Props>(function ProfileInfoSection(
  { hideSaveButton = false, onSaved, showGstCalculator = true, onProfileChange }, ref,
) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [form, setForm] = useState<Form>(EMPTY_FORM);
  // What is stored, as a form — so "unsaved changes" and Discard compare against it.
  const [baseline, setBaseline] = useState<Form>(EMPTY_FORM);
  const [gstDialog, setGstDialog] = useState(false);
  // Company details, address, tax, GST scheme and logo describe the WORKSPACE, and only
  // the Super Admin may change them; anyone else edits their own Full Name and nothing more.
  // The server refuses the rest from them (PATCH /users/me/profile) — this only decides
  // what the form offers.
  const manage = canManageWorkspace(getUser()?.role);

  // Logo state, kept apart from the form: it saves on its own.
  const [logoUrl, setLogoUrl] = useState<string | null>(null);
  const [logoBusy, setLogoBusy] = useState(false);
  const [logoError, setLogoError] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  // The live object URL. Held in a ref as well as in state so it can be revoked
  // without reading stale state from a closure.
  const objectUrl = useRef<string | null>(null);

  const showLogo = useCallback((blob: Blob | null) => {
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    objectUrl.current = blob ? URL.createObjectURL(blob) : null;
    setLogoUrl(objectUrl.current);
  }, []);

  // The <img> cannot fetch this itself — the endpoint needs the bearer token —
  // so the bytes come through axios and are shown from an object URL.
  const fetchLogo = useCallback(async () => {
    try {
      const res = await api.get("/users/me/profile/logo", { responseType: "blob" });
      showLogo(res.data as Blob);
    } catch {
      showLogo(null);   // 404 = the row says there is a logo but the file is gone
    }
  }, [showLogo]);

  const adopt = useCallback((data: Profile) => {
    setProfile(data);
    onProfileChange?.(data);
  }, [onProfileChange]);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const { data } = await api.get<Profile>("/users/me/profile");
        adopt(data);
        setForm(toForm(data));
        setBaseline(toForm(data));
        if (data.has_logo) await fetchLogo();
      } catch (e) { setError(apiError(e)); }
      finally { setLoading(false); }
    })();
    // Once, on mount — `adopt` changes identity with the parent's callback, and
    // re-fetching the profile every time the page re-renders would reset the form.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchLogo]);

  // Release the object URL when the form goes away, or it leaks the image.
  useEffect(() => () => { if (objectUrl.current) URL.revokeObjectURL(objectUrl.current); }, []);

  const set = (k: keyof Form, v: string) => { setForm(p => ({ ...p, [k]: v })); setSaved(false); };

  // For a team member only their name can differ — every other box is locked.
  const editable: (keyof Form)[] = manage ? (Object.keys(form) as (keyof Form)[]) : ["full_name"];
  const dirty = editable.some(k => form[k] !== baseline[k]);

  const save = async (): Promise<boolean> => {
    setError("");
    if (!form.full_name.trim()) { setError("Full name is required."); return false; }
    if (manage && form.pan_number && !PAN_RE.test(form.pan_number.toUpperCase())) {
      setError("Invalid PAN (e.g. ABCDE1234F)."); return false;
    }
    if (manage && form.gst_number && !GSTIN_RE.test(form.gst_number.toUpperCase())) {
      setError("Invalid GSTIN (15 characters)."); return false;
    }
    setSaving(true);
    try {
      // A team member sends their name ALONE: the server refuses any workspace field from
      // them, even unchanged, so the other boxes must not travel at all.
      const body = manage ? {
        full_name: form.full_name.trim(),
        company_name: form.company_name.trim() || null,
        pan_number: form.pan_number.trim().toUpperCase() || null,
        gst_number: form.gst_number.trim().toUpperCase() || null,
        // "" is "no scheme elected" — send NULL so that state has one representation,
        // matching how the address fields are cleared.
        gst_scheme: form.gst_scheme || null,
        address: form.address.trim() || null,
        city: form.city.trim() || null,
        state: form.state.trim() || null,
        pincode: form.pincode.trim() || null,
        country: form.country.trim() || null,
        phone: form.phone.trim() || null,
      } : { full_name: form.full_name.trim() };
      const { data } = await api.patch<Profile>("/users/me/profile", body);
      adopt(data);
      setForm(toForm(data));
      setBaseline(toForm(data));
      setSaved(true);
      onSaved?.();
      return true;
    } catch (e) { setError(apiError(e)); return false; }
    finally { setSaving(false); }
  };

  const discard = () => { setForm(baseline); setError(""); setSaved(false); };

  useImperativeHandle(ref, () => ({ save }));

  const pickLogo = async (file: File | null) => {
    if (!file) return;
    setLogoError("");
    if (!LOGO_TYPES.includes(file.type)) {
      setLogoError("Upload a PNG, JPG or WEBP image."); return;
    }
    if (file.size > MAX_LOGO_BYTES) {
      setLogoError(`That image is ${fileSize(file.size)}. The limit is 2 MB.`); return;
    }
    setLogoBusy(true);
    try {
      const body = new FormData();
      body.append("file", file);
      const { data } = await api.post<Profile>("/users/me/profile/logo", body);
      adopt(data);
      // Show the file that was just picked rather than re-downloading it.
      showLogo(file);
      // Everywhere else that shows it — the sidebar, this page's header — reads the
      // shared store, which has to go and get the new bytes.
      void refreshCompanyLogo();
    } catch (e) { setLogoError(apiError(e)); }
    finally { setLogoBusy(false); }
  };

  const removeLogo = async () => {
    setLogoError("");
    setLogoBusy(true);
    try {
      const { data } = await api.delete<Profile>("/users/me/profile/logo");
      adopt(data);
      showLogo(null);
      void refreshCompanyLogo();
    } catch (e) { setLogoError(apiError(e)); }
    finally { setLogoBusy(false); }
  };

  if (loading) {
    return <div className="py-16 text-center text-xs text-gray-400"><RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" />Loading your profile…</div>;
  }

  const accountType = profile?.tenant_type === "individual" ? "Individual" : "Corporate";
  const hasLogo = Boolean(profile?.has_logo && logoUrl);

  // Live format hints — the same rules save() enforces, shown once a value is long enough
  // to judge rather than on the first keystroke.
  const pan = form.pan_number.toUpperCase();
  const gst = form.gst_number.toUpperCase();
  const panHint = pan.length >= 10 && !PAN_RE.test(pan) ? "Expected 5 letters, 4 digits, 1 letter — e.g. ABCDE1234F." : "";
  const gstHint = gst.length >= 15 && !GSTIN_RE.test(gst) ? "Expected 15 characters — e.g. 07ABCDE1234F1Z5." : "";

  const unknownScheme = form.gst_scheme && !SCHEMES.some(s => s.key === form.gst_scheme);
  const schemeUnsaved = form.gst_scheme !== (profile?.gst_scheme ?? "");

  return (
    <div className="@container">
      <div className="max-w-5xl">
        {!manage && (
          <div className="mb-6">
            <ManagedByAdminNote>
              <strong>Company details, address, tax and GST are managed by your Super Admin.</strong>{" "}
              You can change your own name here.
            </ManagedByAdminNote>
          </div>
        )}
        {/* ── Personal ─────────────────────────────────────────────────────── */}
        <Section icon={User} title="Personal details" description="Who you are on this workspace. Your email is your login and cannot be changed here.">
          <Field label="Full Name *">
            <input value={form.full_name} onChange={e => set("full_name", e.target.value)} placeholder="e.g. Rajesh Kumar" className={INPUT} />
          </Field>
          <div className="grid gap-4 @xl:grid-cols-2">
            <Field label="Email">
              <div className="relative">
                <input value={profile?.email ?? ""} readOnly className={`${READONLY} pr-8`} />
                <Lock className="w-3.5 h-3.5 text-gray-300 absolute right-2.5 top-1/2 -translate-y-1/2" />
              </div>
            </Field>
            <Field label="Account Type">
              <div className="relative">
                <input value={accountType} readOnly className={`${READONLY} pr-8`} />
                <Lock className="w-3.5 h-3.5 text-gray-300 absolute right-2.5 top-1/2 -translate-y-1/2" />
              </div>
            </Field>
          </div>
        </Section>

        {/* ── Company ──────────────────────────────────────────────────────── */}
        <Section icon={Building2} title="Company" locked={!manage} description="How your business appears on the invoices you raise — name, logo and contact line.">
          {/* Logo — saves the moment it is picked, not on Save Changes. */}
          <Field label="Company Logo" error={logoError}>
            <div
              onDragOver={e => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={e => { e.preventDefault(); setDragOver(false); if (manage) void pickLogo(e.dataTransfer.files?.[0] ?? null); }}
              className={`flex items-center gap-4 rounded-xl border p-3 transition-colors ${
                dragOver ? "border-sky-400 bg-sky-50" : "border-gray-200 bg-gray-50/60"
              }`}>
              <div className="w-24 h-24 shrink-0 rounded-xl border border-gray-200 bg-white flex items-center justify-center overflow-hidden shadow-sm">
                {hasLogo ? (
                  // A blob: URL from an auth-gated fetch — next/image cannot optimise
                  // one, and there is no remote URL for it to load.
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={logoUrl!} alt="Company logo" className="max-w-full max-h-full object-contain p-1.5" />
                ) : (
                  <ImageIcon className="w-7 h-7 text-gray-300" />
                )}
              </div>
              <div className="min-w-0">
                {manage && <div className="flex flex-wrap items-center gap-2">
                  <button type="button" onClick={() => fileInput.current?.click()} disabled={logoBusy}
                    className="flex items-center gap-1.5 border border-gray-300 bg-white rounded-lg px-3 py-1.5 text-xs font-semibold text-gray-700 hover:bg-gray-50 disabled:opacity-50">
                    {logoBusy ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
                    {hasLogo ? "Replace logo" : "Upload logo"}
                  </button>
                  {hasLogo && (
                    <button type="button" onClick={removeLogo} disabled={logoBusy}
                      className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold text-red-500 hover:bg-red-50 disabled:opacity-50">
                      <Trash2 className="w-3.5 h-3.5" /> Remove
                    </button>
                  )}
                </div>}
                <p className={`text-[11px] text-gray-400 ${manage ? "mt-1.5" : ""}`}>
                  {manage
                    ? "Drag an image here or upload one — PNG, JPG or WEBP, up to 2 MB. Printed on your invoices."
                    : "Printed on your invoices. Managed by your Super Admin."}
                </p>
                {hasLogo && profile?.logo_name && (
                  <p className="text-[11px] text-gray-500 mt-0.5 truncate">
                    {profile.logo_name}{profile.logo_size ? ` · ${fileSize(profile.logo_size)}` : ""}
                  </p>
                )}
              </div>
              <input ref={fileInput} type="file" accept={LOGO_TYPES.join(",")} className="hidden"
                onChange={e => {
                  const file = e.target.files?.[0] ?? null;
                  // Cleared so picking the same file twice still fires onChange —
                  // otherwise a failed upload cannot be retried with that file.
                  e.target.value = "";
                  void pickLogo(file);
                }} />
            </div>
          </Field>

          <div className="grid gap-4 @xl:grid-cols-2">
            <Field label="Company Name">
              <input value={form.company_name} onChange={e => set("company_name", e.target.value)} placeholder="e.g. ABC Pvt Ltd" className={INPUT} />
            </Field>
            {/* The BUSINESS's line, not this user's — it heads every invoice this
                workspace prints. Two numbers separated by a comma stack on the letterhead
                the way a printed one does. */}
            <Field label="Phone" hint="Printed on your invoices. Separate two numbers with a comma.">
              <input value={form.phone} onChange={e => set("phone", e.target.value)} maxLength={100}
                placeholder="9911194525, 9810316453" className={INPUT} />
            </Field>
          </div>
        </Section>

        {/* ── Address ──────────────────────────────────────────────────────── */}
        <Section icon={MapPin} title="Registered address" locked={!manage} description="Your business address, as printed on invoices. The state also decides whether a sale is billed as CGST + SGST or IGST.">
          <Field label="Address">
            <textarea value={form.address} onChange={e => set("address", e.target.value)} rows={2}
              placeholder="e.g. 402, Sunrise Tower, MG Road" className={`${INPUT} resize-y`} />
          </Field>
          <div className="grid gap-4 @xl:grid-cols-2 @3xl:grid-cols-4">
            <Field label="City">
              <input value={form.city} onChange={e => set("city", e.target.value)} placeholder="e.g. Mumbai" className={INPUT} />
            </Field>
            <Field label="State">
              <input value={form.state} onChange={e => set("state", e.target.value)} placeholder="e.g. Maharashtra" className={INPUT} />
            </Field>
            <Field label="Pincode">
              <input value={form.pincode} onChange={e => set("pincode", e.target.value)} maxLength={10} placeholder="400069" className={INPUT} />
            </Field>
            <Field label="Country">
              <input value={form.country} onChange={e => set("country", e.target.value)} placeholder="India" className={INPUT} />
            </Field>
          </div>
        </Section>

        {/* ── Tax ──────────────────────────────────────────────────────────── */}
        <Section icon={Receipt} title="Tax & GST" description="Your tax identity, and how this workspace charges GST. One scheme applies to everyone on the workspace.">
          {/* Locked by hand rather than with Section's `locked`: the "How GST is calculated"
              button below must stay usable — reading the rules is not changing them. */}
          <fieldset disabled={!manage} className={`grid gap-4 @xl:grid-cols-2 ${!manage ? LOCKED : ""}`}>
            <Field label="PAN Number" error={panHint}>
              <input value={form.pan_number} onChange={e => set("pan_number", e.target.value.toUpperCase())} maxLength={10}
                placeholder="ABCDE1234F" className={`${INPUT} font-mono uppercase ${panHint ? "border-red-300" : ""}`} />
            </Field>
            <Field label="GST Number" error={gstHint}>
              <input value={form.gst_number} onChange={e => set("gst_number", e.target.value.toUpperCase())} maxLength={15}
                placeholder="22ABCDE1234F1Z5" className={`${INPUT} font-mono uppercase ${gstHint ? "border-red-300" : ""}`} />
            </Field>
          </fieldset>

          {/* Which scheme this workspace bills under. Sits with PAN / GSTIN because it is the
              same kind of fact — those say WHO the business is for tax, this says HOW it
              taxes. One choice for the whole workspace: Rule 32(3) is an election made by
              the registered person, so two colleagues cannot bill differently. */}
          <div>
            <div className="flex items-end justify-between gap-3 mb-1.5">
              {/* LABEL's own spacing, minus its mb-1: the row aligns it with the button. */}
              <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide">
                GST Configuration
                {schemeUnsaved && <span className="ml-1.5 normal-case tracking-normal text-amber-600">· not saved yet</span>}
              </label>
              {showGstCalculator && (
                <button type="button" onClick={() => setGstDialog(true)}
                  className="flex items-center gap-1.5 text-[11px] font-semibold text-violet-600 hover:text-violet-800">
                  <Calculator className="w-3.5 h-3.5" /> How GST is calculated
                </button>
              )}
            </div>

            <fieldset disabled={!manage} className="grid gap-3 @xl:grid-cols-2" role="radiogroup" aria-label="GST configuration">
              {SCHEMES.map(s => {
                const active = form.gst_scheme === s.key;
                return (
                  <button key={s.key} type="button" role="radio" aria-checked={active}
                    onClick={() => set("gst_scheme", s.key)}
                    className={`text-left rounded-xl border p-3.5 transition-all disabled:cursor-not-allowed ${!manage && !active ? "opacity-50" : ""} ${
                      active
                        ? "border-[#1e4d8c] bg-[#1e4d8c]/[0.04] ring-1 ring-[#1e4d8c]"
                        : "border-gray-200 bg-white hover:border-gray-300 hover:bg-gray-50/60"
                    }`}>
                    <div className="flex items-center justify-between">
                      <span className="text-[13px] font-bold text-gray-900">{s.label}</span>
                      <span className={`w-4.5 h-4.5 rounded-full border flex items-center justify-center ${
                        active ? "bg-[#1e4d8c] border-[#1e4d8c]" : "border-gray-300 bg-white"
                      }`}>
                        {active && <Check className="w-3 h-3 text-white" />}
                      </span>
                    </div>
                    <p className="text-[11px] text-gray-500 mt-1 leading-relaxed">{SCHEME_SUMMARY[s.key]}</p>
                  </button>
                );
              })}
            </fieldset>

            {/* A slug saved by a newer version would otherwise vanish silently on the next
                save. Keep it visible so nothing is dropped unnoticed. */}
            {unknownScheme && (
              <p className="flex items-center gap-1.5 text-[11px] text-amber-700 mt-2">
                <AlertTriangle className="w-3.5 h-3.5" />
                Saved as <strong>{form.gst_scheme}</strong>, which this version does not recognise — pick one above.
              </p>
            )}
            <div className="flex items-center justify-between mt-2">
              <p className="text-[10px] text-gray-400">The rates themselves are maintained by the platform team.</p>
              {manage && form.gst_scheme && (
                <button type="button" onClick={() => set("gst_scheme", "")}
                  className="text-[10px] font-semibold text-gray-400 hover:text-gray-600">
                  Clear selection
                </button>
              )}
            </div>
          </div>
        </Section>
      </div>

      {/* ── Save ───────────────────────────────────────────────────────────── */}
      {/* Sticky, so it stays in reach at the bottom of the screen while the form scrolls —
          and only asks for attention once there is something to save. In the wizard the
          Next button saves instead, so there is no bar at all. */}
      {!hideSaveButton && (
        // Bleeds to the edges of the page's card (p-6 in profile/page.tsx) so it reads as
        // the card's footer rather than a box floating inside it.
        <div className="sticky bottom-0 z-10 -mx-6 -mb-6 mt-2 px-6 py-3 bg-white/95 backdrop-blur border-t border-gray-200 rounded-b-2xl flex items-center justify-between gap-3">
          <div className="text-[11px] min-w-0">
            {error ? (
              <p className="text-red-500 truncate">{error}</p>
            ) : dirty ? (
              <p className="flex items-center gap-1.5 text-amber-600 font-semibold">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-500" /> You have unsaved changes
              </p>
            ) : saved ? (
              <p className="flex items-center gap-1.5 text-green-600"><CheckCircle2 className="w-3.5 h-3.5" /> All changes saved</p>
            ) : (
              <p className="text-gray-400">
                {manage
                  ? "Your logo saves as soon as you pick it; everything else saves here."
                  : "You can change your own name here."}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {dirty && (
              <button onClick={discard} disabled={saving}
                className="flex items-center gap-1.5 border border-gray-200 rounded-lg px-3.5 py-2 text-xs font-semibold text-gray-600 hover:bg-gray-50 disabled:opacity-50">
                <RotateCcw className="w-3.5 h-3.5" /> Discard
              </button>
            )}
            <button onClick={save} disabled={saving || !dirty}
              className="text-white rounded-lg px-5 py-2 text-xs font-semibold disabled:opacity-40"
              style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
              {saving ? "Saving…" : "Save Changes"}
            </button>
          </div>
        </div>
      )}

      {/* In the wizard there is no bar, so errors still need somewhere to show. */}
      {hideSaveButton && error && <p className="text-[11px] text-red-500 mt-3">{error}</p>}

      {gstDialog && (
        <GstSchemeDialog
          selected={form.gst_scheme}
          onUse={manage ? s => set("gst_scheme", s) : undefined}
          onClose={() => setGstDialog(false)}
        />
      )}
    </div>
  );
});

export default ProfileInfoSection;
