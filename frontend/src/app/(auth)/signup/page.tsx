"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Eye, EyeOff, Building2, User, CheckCircle2, AlertTriangle } from "lucide-react";
import { setToken, setUser } from "@/lib/auth";

type AccountType = "corporate" | "individual";

// client-side mirrors of the backend rules (server is authoritative)
const PAN_RE   = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
const GSTIN_RE = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;
const PUBLIC_DOMAINS = new Set([
  "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "yahoo.in", "ymail.com",
  "outlook.com", "hotmail.com", "live.com", "msn.com", "icloud.com", "me.com",
  "aol.com", "proton.me", "protonmail.com", "rediffmail.com", "zoho.com",
  "gmx.com", "mail.com", "yandex.com",
]);

export default function SignupPage() {
  const router = useRouter();
  const [accountType,  setAccountType]  = useState<AccountType>("corporate");
  const [fullName,     setFullName]     = useState("");
  const [email,        setEmail]        = useState("");
  const [companyName,  setCompanyName]  = useState("");
  const [pan,          setPan]          = useState("");
  const [gstRegistered, setGstRegistered] = useState(false);
  const [gst,          setGst]          = useState("");
  const [password,     setPassword]     = useState("");
  const [confirm,      setConfirm]      = useState("");
  const [showPw,       setShowPw]       = useState(false);
  const [loading,      setLoading]      = useState(false);
  const [error,        setError]        = useState("");
  const [domainNote,   setDomainNote]   = useState("");  // corporate: "you'll be admin"
  const [publicWarn,   setPublicWarn]   = useState("");  // corporate + public domain
  const [panError,     setPanError]     = useState("");
  const [gstError,     setGstError]     = useState("");

  const isIndividual = accountType === "individual";

  const switchType = (t: AccountType) => {
    setAccountType(t);
    setError(""); setPanError(""); setGstError(""); setPublicWarn(""); setDomainNote("");
    // re-evaluate domain hints for the new type
    evaluateDomain(email, t);
  };

  const evaluateDomain = (v: string, type: AccountType) => {
    const parts = v.split("@");
    const domain = parts.length === 2 ? parts[1].toLowerCase() : "";
    if (type === "corporate" && domain.includes(".")) {
      if (PUBLIC_DOMAINS.has(domain)) {
        setPublicWarn("That's a personal email. Use your work email, or switch to Individual.");
        setDomainNote("");
      } else {
        setDomainNote(`Domain: ${domain} — you'll be the admin for this workspace.`);
        setPublicWarn("");
      }
    } else {
      setDomainNote(""); setPublicWarn("");
    }
  };

  const handleEmailChange = (v: string) => {
    setEmail(v);
    setError("");
    evaluateDomain(v, accountType);
  };

  const handlePanChange = (v: string) => {
    const up = v.toUpperCase();
    setPan(up);
    setPanError(up && !PAN_RE.test(up) ? "Invalid PAN (e.g. ABCDE1234F)." : "");
  };

  const handleGstChange = (v: string) => {
    const up = v.toUpperCase();
    setGst(up);
    setGstError(up && !GSTIN_RE.test(up) ? "Invalid GSTIN (15 characters)." : "");
  };

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!fullName || !email || !password || !confirm) {
      setError("Please fill in all required fields."); return;
    }
    const domain = email.split("@")[1]?.toLowerCase() ?? "";
    if (!isIndividual && PUBLIC_DOMAINS.has(domain)) {
      setError("Corporate accounts need a work email. Switch to Individual to use a personal email."); return;
    }
    if (isIndividual && !pan) {
      setError("PAN number is required for individual accounts."); return;
    }
    if (pan && !PAN_RE.test(pan)) {
      setError("Please enter a valid PAN (e.g. ABCDE1234F)."); return;
    }
    if (gstRegistered && (!gst || !GSTIN_RE.test(gst))) {
      setError("Please enter a valid 15-character GSTIN, or turn off GST registered."); return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters."); return;
    }
    if (password !== confirm) {
      setError("Passwords do not match."); return;
    }

    setLoading(true);
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1"}/auth/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          account_type:  accountType,
          full_name:     fullName,
          email,
          password,
          company_name:  isIndividual ? null : (companyName || null),
          pan_number:    pan || null,
          gst_registered: gstRegistered,
          gst_number:    gstRegistered ? gst : null,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        // FastAPI: string detail (HTTPException) or array of validation errors (422)
        const d = data?.detail;
        const msg = typeof d === "string"
          ? d
          : Array.isArray(d)
            ? (d[0]?.msg?.replace(/^Value error,\s*/, "") ?? "Signup failed. Please try again.")
            : "Signup failed. Please try again.";
        setError(msg);
        return;
      }
      setToken(data.access_token);
      setUser(data.user);
      router.push("/dashboard");
    } catch {
      setError("Cannot reach server. Make sure the backend is running.");
    } finally {
      setLoading(false);
    }
  };

  const inputCls =
    "w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30 focus:border-[#1e3a5f] transition-colors";

  return (
    <div className="w-full max-w-md">
      {/* mobile logo */}
      <div className="lg:hidden flex items-center gap-2 mb-8">
        <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: "#1e3a5f" }}>
          <svg className="w-4 h-4 text-white" viewBox="0 0 24 24" fill="currentColor">
            <path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z"/>
          </svg>
        </div>
        <span className="font-bold text-gray-900">AirYield</span>
      </div>

      <div className="mb-5">
        <h1 className="text-2xl font-bold text-gray-900">Create your account</h1>
        <p className="text-sm text-gray-500 mt-1">
          {isIndividual
            ? "Set up your personal workspace — private to you."
            : "Set up your company workspace — you'll be the admin."}
        </p>
      </div>

      {/* account-type segmented toggle */}
      <div className="grid grid-cols-2 gap-2 mb-5">
        {([
          { t: "corporate" as const,  label: "Corporate", sub: "Company / work email", Icon: Building2 },
          { t: "individual" as const, label: "Individual", sub: "Personal email is fine", Icon: User },
        ]).map(({ t, label, sub, Icon }) => {
          const active = accountType === t;
          return (
            <button
              key={t}
              type="button"
              onClick={() => switchType(t)}
              className={`flex flex-col items-start gap-0.5 rounded-xl border px-3.5 py-2.5 text-left transition-colors ${
                active
                  ? "border-[#1e3a5f] bg-[#1e3a5f] text-white"
                  : "border-gray-200 text-gray-600 hover:border-gray-300"
              }`}>
              <span className="flex items-center gap-1.5 text-sm font-semibold">
                <Icon className="w-4 h-4"/> {label}
              </span>
              <span className={`text-[11px] ${active ? "text-white/70" : "text-gray-400"}`}>{sub}</span>
            </button>
          );
        })}
      </div>

      {/* context banner */}
      {isIndividual ? (
        <div className="flex items-start gap-2.5 bg-gray-50 border border-gray-200 rounded-xl px-3.5 py-2.5 mb-5">
          <User className="w-4 h-4 text-gray-500 flex-shrink-0 mt-0.5"/>
          <p className="text-[11px] text-gray-600 leading-snug">
            <span className="font-semibold">Private workspace.</span>{" "}
            Only you have access. Any email works, including Gmail or Yahoo.
          </p>
        </div>
      ) : (
        <div className="flex items-start gap-2.5 bg-blue-50 border border-blue-200 rounded-xl px-3.5 py-2.5 mb-5">
          <Building2 className="w-4 h-4 text-blue-500 flex-shrink-0 mt-0.5"/>
          <p className="text-[11px] text-blue-700 leading-snug">
            <span className="font-semibold">One admin per company.</span>{" "}
            The first person from your work domain becomes the admin. Teammates are
            added later from User Management.
          </p>
        </div>
      )}

      <form onSubmit={handleSignup} className="space-y-3.5">
        {/* full name */}
        <div>
          <label className="block text-xs font-semibold text-gray-700 mb-1.5">Full Name *</label>
          <input
            type="text"
            value={fullName}
            onChange={e => setFullName(e.target.value)}
            placeholder="e.g. Rajesh Kumar"
            className={inputCls}
          />
        </div>

        {/* email */}
        <div>
          <label className="block text-xs font-semibold text-gray-700 mb-1.5">
            {isIndividual ? "Email *" : "Work Email *"}
          </label>
          <input
            type="email"
            value={email}
            onChange={e => handleEmailChange(e.target.value)}
            placeholder={isIndividual ? "you@example.com" : "you@yourcompany.com"}
            className={inputCls}
          />
          {!isIndividual && domainNote && (
            <div className="flex items-center gap-1.5 mt-1.5">
              <CheckCircle2 className="w-3.5 h-3.5 text-green-500"/>
              <p className="text-[11px] text-green-600 font-medium">{domainNote}</p>
            </div>
          )}
          {!isIndividual && publicWarn && (
            <div className="flex items-center gap-1.5 mt-1.5">
              <AlertTriangle className="w-3.5 h-3.5 text-amber-500"/>
              <p className="text-[11px] text-amber-600 font-medium">{publicWarn}</p>
            </div>
          )}
        </div>

        {/* company name — corporate only */}
        {!isIndividual && (
          <div>
            <label className="block text-xs font-semibold text-gray-700 mb-1.5">
              Company Name <span className="text-gray-400 font-normal">(optional)</span>
            </label>
            <input
              type="text"
              value={companyName}
              onChange={e => setCompanyName(e.target.value)}
              placeholder="e.g. Yatra Online Pvt Ltd"
              className={inputCls}
            />
          </div>
        )}

        {/* PAN — required for individual, optional for corporate */}
        <div>
          <label className="block text-xs font-semibold text-gray-700 mb-1.5">
            PAN Number {isIndividual
              ? <span className="text-red-500">*</span>
              : <span className="text-gray-400 font-normal">(optional)</span>}
          </label>
          <input
            type="text"
            value={pan}
            onChange={e => handlePanChange(e.target.value)}
            placeholder="ABCDE1234F"
            maxLength={10}
            className={`${inputCls} uppercase ${panError ? "border-red-300 focus:ring-red-200" : ""}`}
          />
          {panError && <p className="text-[11px] text-red-500 mt-1">{panError}</p>}
        </div>

        {/* GST registered toggle — both flows */}
        <div>
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={gstRegistered}
              onChange={e => { setGstRegistered(e.target.checked); if (!e.target.checked) { setGst(""); setGstError(""); } }}
              className="w-4 h-4 rounded border-gray-300 text-[#1e3a5f] focus:ring-[#1e3a5f]/30"
            />
            <span className="text-xs font-semibold text-gray-700">Are you GST registered?</span>
          </label>
          {gstRegistered && (
            <div className="mt-2">
              <input
                type="text"
                value={gst}
                onChange={e => handleGstChange(e.target.value)}
                placeholder="GSTIN — e.g. 22ABCDE1234F1Z5"
                maxLength={15}
                className={`${inputCls} uppercase ${gstError ? "border-red-300 focus:ring-red-200" : ""}`}
              />
              {gstError && <p className="text-[11px] text-red-500 mt-1">{gstError}</p>}
            </div>
          )}
        </div>

        {/* password */}
        <div>
          <label className="block text-xs font-semibold text-gray-700 mb-1.5">Password *</label>
          <div className="relative">
            <input
              type={showPw ? "text" : "password"}
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="Min 8 characters"
              className={`${inputCls} pr-10`}
            />
            <button type="button" onClick={() => setShowPw(s => !s)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
              {showPw ? <EyeOff className="w-4 h-4"/> : <Eye className="w-4 h-4"/>}
            </button>
          </div>
        </div>

        {/* confirm */}
        <div>
          <label className="block text-xs font-semibold text-gray-700 mb-1.5">Confirm Password *</label>
          <input
            type="password"
            value={confirm}
            onChange={e => setConfirm(e.target.value)}
            placeholder="Re-enter your password"
            className={`w-full border rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 transition-colors ${
              confirm && confirm !== password
                ? "border-red-300 focus:ring-red-200"
                : "border-gray-200 focus:ring-[#1e3a5f]/30 focus:border-[#1e3a5f]"
            }`}
          />
          {confirm && confirm !== password && (
            <p className="text-[11px] text-red-500 mt-1">Passwords do not match</p>
          )}
        </div>

        {/* error */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2.5 text-xs text-red-600 leading-snug">
            {error}
          </div>
        )}

        {/* submit */}
        <button
          type="submit"
          disabled={loading}
          className="w-full text-white py-3 rounded-xl font-semibold text-sm hover:opacity-90 disabled:opacity-60 transition-all"
          style={{ background: "#1e3a5f" }}>
          {loading ? "Creating account..." : "Create Account"}
        </button>
      </form>

      <p className="text-center text-sm text-gray-600 mt-5">
        Already have an account?{" "}
        <Link href="/login" className="font-semibold text-[#1e3a5f] hover:underline">
          Sign in
        </Link>
      </p>
    </div>
  );
}
