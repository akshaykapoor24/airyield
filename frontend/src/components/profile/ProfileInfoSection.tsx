"use client";

// User information form (My Profile + onboarding step 1). Bound to
// GET/PATCH /users/me/profile. Email and account type are read-only; full name,
// company, PAN and GST are editable. Exposes save() so the onboarding wizard can
// persist on "Next".

import { useState, useEffect, forwardRef, useImperativeHandle } from "react";
import { RefreshCw, CheckCircle2 } from "lucide-react";
import api from "@/lib/api";
import { INPUT, LABEL, apiError } from "@/components/userMaster/shared";

const PAN_RE = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
const GSTIN_RE = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;

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
};

export type ProfileInfoHandle = { save: () => Promise<boolean> };

type Props = { hideSaveButton?: boolean; onSaved?: () => void };

const ProfileInfoSection = forwardRef<ProfileInfoHandle, Props>(function ProfileInfoSection(
  { hideSaveButton = false, onSaved }, ref,
) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [form, setForm] = useState({ full_name: "", company_name: "", pan_number: "", gst_number: "" });

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
        });
      } catch (e) { setError(apiError(e)); }
      finally { setLoading(false); }
    })();
  }, []);

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
      });
      setProfile(data);
      setSaved(true);
      onSaved?.();
      return true;
    } catch (e) { setError(apiError(e)); return false; }
    finally { setSaving(false); }
  };

  useImperativeHandle(ref, () => ({ save }));

  if (loading) {
    return <div className="py-12 text-center text-xs text-gray-400"><RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" />Loading…</div>;
  }

  const accountType = profile?.tenant_type === "individual" ? "Individual" : "Corporate";

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

      <div>
        <label className={LABEL}>Full Name *</label>
        <input value={form.full_name} onChange={e => set("full_name", e.target.value)} placeholder="e.g. Rajesh Kumar" className={INPUT} />
      </div>

      <div>
        <label className={LABEL}>Company Name</label>
        <input value={form.company_name} onChange={e => set("company_name", e.target.value)} placeholder="e.g. ABC Pvt Ltd" className={INPUT} />
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
