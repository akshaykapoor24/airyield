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

import { useState, useEffect, useRef, forwardRef, useImperativeHandle, useCallback } from "react";
import { RefreshCw, CheckCircle2, ImageIcon, Upload, Trash2 } from "lucide-react";
import api from "@/lib/api";
import { INPUT, LABEL, apiError } from "@/components/userMaster/shared";
import GstSchemePreview from "@/components/profile/GstSchemePreview";

// The three schemes a workspace can bill under. Mirrors GST_SCHEMES /
// SCHEME_LABELS in backend/app/models/gst_configuration.py — the backend rejects
// anything else with a 422, so these must stay in step.
// The two bases a workspace can elect. Each spans two rules, and nothing here
// picks between them — a ticket's sector decides for Abatement, and a customer's
// own billing type decides for Normal.
const GST_SCHEMES = [
  { value: "abatement", label: "Abatement" },
  { value: "normal",    label: "Normal" },
] as const;

// A one-line plain-English summary per scheme, so the dropdown still explains
// itself where the full calculator is hidden (the onboarding wizard). Static —
// it describes what is taxed, never a rate, so it cannot go stale when the
// platform revises one.
const SCHEME_HELP: Record<string, string> = {
  abatement: "GST on a deemed slice of the basic fare — 5% domestic, 10% international, by ticket sector.",
  normal: "GST on actual consideration — an agency customer's service charge, or a reseller's whole sale. Set per customer in User master.",
};

const PAN_RE = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
const GSTIN_RE = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;

// Mirrors MAX_LOGO_BYTES in backend/app/api/v1/users.py. Checked here as well so
// an oversized pick is refused instantly instead of after the upload.
const MAX_LOGO_BYTES = 2 * 1024 * 1024;
const LOGO_TYPES = ["image/png", "image/jpeg", "image/webp"];

type Profile = {
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
  /** Show the worked GST calculation under the scheme dropdown.
   *
   *  Off in the onboarding wizard: a tax calculator with three number inputs is
   *  a lot to meet before you have typed your company name, inside a modal that
   *  already scrolls. The dropdown itself stays — electing a scheme is workspace
   *  setup exactly like PAN and GSTIN, which step 1 already collects.
   *
   *  Deliberately NOT keyed off `hideSaveButton`. That prop means one thing —
   *  "the wizard's Next button saves, so hide mine" — and overloading it to also
   *  mean "we are in the wizard" would make the next edit here ambiguous. */
  showGstCalculator?: boolean;
};

function fileSize(bytes: number | null): string {
  if (!bytes) return "";
  return bytes < 1024 * 1024 ? `${Math.round(bytes / 1024)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

const ProfileInfoSection = forwardRef<ProfileInfoHandle, Props>(function ProfileInfoSection(
  { hideSaveButton = false, onSaved, showGstCalculator = true }, ref,
) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [form, setForm] = useState({
    full_name: "", company_name: "", pan_number: "", gst_number: "", gst_scheme: "",
    address: "", city: "", state: "", pincode: "", country: "", phone: "",
  });

  // Logo state, kept apart from the form: it saves on its own.
  const [logoUrl, setLogoUrl] = useState<string | null>(null);
  const [logoBusy, setLogoBusy] = useState(false);
  const [logoError, setLogoError] = useState("");
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

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const { data } = await api.get<Profile>("/users/me/profile");
        setProfile(data);
        setForm({
          full_name: data.full_name ?? "",
          company_name: data.company_name ?? "",
          pan_number: data.pan_number ?? "",
          gst_number: data.gst_number ?? "",
          gst_scheme: data.gst_scheme ?? "",
          address: data.address ?? "",
          city: data.city ?? "",
          state: data.state ?? "",
          pincode: data.pincode ?? "",
          country: data.country ?? "",
          phone: data.phone ?? "",
        });
        if (data.has_logo) await fetchLogo();
      } catch (e) { setError(apiError(e)); }
      finally { setLoading(false); }
    })();
  }, [fetchLogo]);

  // Release the object URL when the form goes away, or it leaks the image.
  useEffect(() => () => { if (objectUrl.current) URL.revokeObjectURL(objectUrl.current); }, []);

  const set = (k: keyof typeof form, v: string) => { setForm(p => ({ ...p, [k]: v })); setSaved(false); };

  const save = async (): Promise<boolean> => {
    setError("");
    if (!form.full_name.trim()) { setError("Full name is required."); return false; }
    if (form.pan_number && !PAN_RE.test(form.pan_number.toUpperCase())) {
      setError("Invalid PAN (e.g. ABCDE1234F)."); return false;
    }
    if (form.gst_number && !GSTIN_RE.test(form.gst_number.toUpperCase())) {
      setError("Invalid GSTIN (15 characters)."); return false;
    }
    setSaving(true);
    try {
      const { data } = await api.patch<Profile>("/users/me/profile", {
        full_name: form.full_name.trim(),
        company_name: form.company_name.trim() || null,
        pan_number: form.pan_number.trim().toUpperCase() || null,
        gst_number: form.gst_number.trim().toUpperCase() || null,
        // "" is the cleared dropdown — send NULL so "not elected" has one
        // representation, matching how the address fields are cleared.
        gst_scheme: form.gst_scheme || null,
        address: form.address.trim() || null,
        city: form.city.trim() || null,
        state: form.state.trim() || null,
        pincode: form.pincode.trim() || null,
        country: form.country.trim() || null,
        phone: form.phone.trim() || null,
      });
      setProfile(data);
      setSaved(true);
      onSaved?.();
      return true;
    } catch (e) { setError(apiError(e)); return false; }
    finally { setSaving(false); }
  };

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
      setProfile(data);
      // Show the file that was just picked rather than re-downloading it.
      showLogo(file);
    } catch (e) { setLogoError(apiError(e)); }
    finally { setLogoBusy(false); }
  };

  const removeLogo = async () => {
    setLogoError("");
    setLogoBusy(true);
    try {
      const { data } = await api.delete<Profile>("/users/me/profile/logo");
      setProfile(data);
      showLogo(null);
    } catch (e) { setLogoError(apiError(e)); }
    finally { setLogoBusy(false); }
  };

  if (loading) {
    return <div className="py-12 text-center text-xs text-gray-400"><RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" />Loading…</div>;
  }

  const accountType = profile?.tenant_type === "individual" ? "Individual" : "Corporate";
  const hasLogo = Boolean(profile?.has_logo && logoUrl);

  return (
    <div className="space-y-3 max-w-2xl">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL}>Email (read-only)</label>
          <input value={profile?.email ?? ""} readOnly
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-gray-100 text-gray-500 cursor-not-allowed focus:outline-none" />
        </div>
        <div>
          <label className={LABEL}>Account Type</label>
          <input value={accountType} readOnly
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-gray-100 text-gray-500 cursor-not-allowed focus:outline-none" />
        </div>
      </div>

      {/* Company logo — saves on pick, not on Save Changes. */}
      <div>
        <label className={LABEL}>Company Logo</label>
        <div className="flex items-center gap-4 border border-gray-200 rounded-lg p-3 bg-gray-50">
          <div className="w-28 h-20 shrink-0 rounded-lg border border-dashed border-gray-300 bg-white flex items-center justify-center overflow-hidden">
            {hasLogo ? (
              // A blob: URL from an auth-gated fetch — next/image cannot optimise
              // one, and there is no remote URL for it to load.
              // eslint-disable-next-line @next/next/no-img-element
              <img src={logoUrl!} alt="Company logo" className="max-w-full max-h-full object-contain" />
            ) : (
              <ImageIcon className="w-6 h-6 text-gray-300" />
            )}
          </div>

          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <button type="button" onClick={() => fileInput.current?.click()} disabled={logoBusy}
                className="flex items-center gap-1.5 border border-gray-300 bg-white rounded-lg px-3 py-1.5 text-xs font-semibold text-gray-700 hover:bg-gray-50 disabled:opacity-50">
                {logoBusy
                  ? <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                  : <Upload className="w-3.5 h-3.5" />}
                {hasLogo ? "Replace logo" : "Upload logo"}
              </button>
              {hasLogo && (
                <button type="button" onClick={removeLogo} disabled={logoBusy}
                  className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold text-red-500 hover:bg-red-50 disabled:opacity-50">
                  <Trash2 className="w-3.5 h-3.5" /> Remove
                </button>
              )}
            </div>
            <p className="text-[11px] text-gray-400 mt-1.5">
              PNG, JPG or WEBP · up to 2 MB. Printed on the invoices you raise.
            </p>
            {hasLogo && profile?.logo_name && (
              <p className="text-[11px] text-gray-500 mt-0.5 truncate">
                {profile.logo_name}{profile.logo_size ? ` · ${fileSize(profile.logo_size)}` : ""}
              </p>
            )}
            {logoError && <p className="text-[11px] text-red-500 mt-1">{logoError}</p>}
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
      </div>

      <div>
        <label className={LABEL}>Full Name *</label>
        <input value={form.full_name} onChange={e => set("full_name", e.target.value)} placeholder="e.g. Rajesh Kumar" className={INPUT} />
      </div>

      <div>
        <label className={LABEL}>Company Name</label>
        <input value={form.company_name} onChange={e => set("company_name", e.target.value)} placeholder="e.g. ABC Pvt Ltd" className={INPUT} />
      </div>

      <div>
        <label className={LABEL}>Address</label>
        <textarea value={form.address} onChange={e => set("address", e.target.value)} rows={2}
          placeholder="e.g. 402, Sunrise Tower, MG Road" className={`${INPUT} resize-y`} />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL}>City</label>
          <input value={form.city} onChange={e => set("city", e.target.value)} placeholder="e.g. Mumbai" className={INPUT} />
        </div>
        <div>
          <label className={LABEL}>State</label>
          <input value={form.state} onChange={e => set("state", e.target.value)} placeholder="e.g. Maharashtra" className={INPUT} />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL}>Pincode</label>
          <input value={form.pincode} onChange={e => set("pincode", e.target.value)} maxLength={10} placeholder="400069" className={INPUT} />
        </div>
        <div>
          <label className={LABEL}>Country</label>
          <input value={form.country} onChange={e => set("country", e.target.value)} placeholder="India" className={INPUT} />
        </div>
      </div>

      {/* The BUSINESS's line, not this user's — it heads every invoice this
          workspace prints, beside the address above. Two numbers separated by a
          comma or a newline stack on the letterhead the way a printed one does. */}
      <div>
        <label className={LABEL}>Phone</label>
        <input value={form.phone} onChange={e => set("phone", e.target.value)} maxLength={100}
          placeholder="9911194525, 9810316453" className={INPUT} />
        <p className="text-[10px] text-gray-400 mt-1">
          Printed at the top of the invoices you raise. Separate two numbers with a comma.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL}>PAN Number</label>
          <input value={form.pan_number} onChange={e => set("pan_number", e.target.value.toUpperCase())} maxLength={10} placeholder="ABCDE1234F" className={`${INPUT} uppercase`} />
        </div>
        <div>
          <label className={LABEL}>GST Number</label>
          <input value={form.gst_number} onChange={e => set("gst_number", e.target.value.toUpperCase())} maxLength={15} placeholder="22ABCDE1234F1Z5" className={`${INPUT} uppercase`} />
        </div>
      </div>

      {/* Which scheme this workspace bills under. Sits with PAN / GSTIN because
          it is the same kind of fact — those say WHO the business is for tax,
          this says HOW it taxes. One choice for the whole workspace: Rule 32(3)
          is an election made by the registered person, so two colleagues cannot
          bill differently. */}
      <div>
        <label className={LABEL}>GST Configuration</label>
        <select value={form.gst_scheme} onChange={e => set("gst_scheme", e.target.value)} className={INPUT}>
          <option value="">— Select GST configuration —</option>
          {/* A slug saved by a newer version would otherwise vanish silently on
              the next save. Keep it visible so nothing is dropped unnoticed. */}
          {form.gst_scheme && !GST_SCHEMES.some(s => s.value === form.gst_scheme) && (
            <option value={form.gst_scheme}>{form.gst_scheme}</option>
          )}
          {GST_SCHEMES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
        <p className="text-[10px] text-gray-400 mt-1">
          {SCHEME_HELP[form.gst_scheme] ??
            "How this workspace charges GST. The rates themselves are maintained by the platform team."}
          {/* The panel below shows the UNSAVED selection, so say when it is not
              recorded yet — the same amber "unsaved" cue the master editor uses. */}
          {form.gst_scheme !== (profile?.gst_scheme ?? "") && (
            <span className="text-amber-600 font-semibold"> · not saved yet</span>
          )}
        </p>
      </div>

      {showGstCalculator && <GstSchemePreview scheme={form.gst_scheme} />}

      {error && <p className="text-[11px] text-red-500">{error}</p>}
      {saved && !error && (
        <p className="flex items-center gap-1.5 text-[11px] text-green-600"><CheckCircle2 className="w-3.5 h-3.5" /> Saved.</p>
      )}

      {!hideSaveButton && (
        <div className="pt-1">
          <button onClick={save} disabled={saving}
            className="text-white rounded-lg px-5 py-2 text-sm font-semibold disabled:opacity-50"
            style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
            {saving ? "Saving…" : "Save Changes"}
          </button>
        </div>
      )}
    </div>
  );
});

export default ProfileInfoSection;
