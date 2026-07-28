"use client";

import { useState } from "react";
import Link from "next/link";
import {
  AlertTriangle, ArrowRight, Building2, CheckCircle2, CreditCard, Eye, EyeOff,
  Loader2, Lock, Mail, MailCheck, ReceiptText, TriangleAlert, User,
} from "lucide-react";

type AccountType = "corporate" | "individual";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

// client-side mirrors of the backend rules (server is authoritative)
const PAN_RE   = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
const GSTIN_RE = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;
const PUBLIC_DOMAINS = new Set([
  "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "yahoo.in", "ymail.com",
  "outlook.com", "hotmail.com", "live.com", "msn.com", "icloud.com", "me.com",
  "aol.com", "proton.me", "protonmail.com", "rediffmail.com", "zoho.com",
  "gmx.com", "mail.com", "yandex.com",
]);

/** Purely visual strength hint — the server enforces the real rule (min 8). */
function strengthOf(pw: string) {
  if (!pw) return { score: 0, label: "", tone: "" };
  let score = 0;
  if (pw.length >= 8) score++;
  if (pw.length >= 12) score++;
  if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) score++;
  if (/\d/.test(pw) && /[^A-Za-z0-9]/.test(pw)) score++;
  const meta = [
    { label: "Too short", tone: "bg-red-500 text-red-600" },
    { label: "Weak",      tone: "bg-orange-500 text-orange-600" },
    { label: "Fair",      tone: "bg-amber-500 text-amber-600" },
    { label: "Strong",    tone: "bg-emerald-500 text-emerald-600" },
    { label: "Excellent", tone: "bg-emerald-600 text-emerald-700" },
  ][score];
  return { score, ...meta };
}

export default function SignupPage() {
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
  // post-signup confirmation ("check your email")
  const [sent,         setSent]         = useState(false);
  const [devVerifyUrl, setDevVerifyUrl] = useState<string | null>(null);
  const [resendMsg,    setResendMsg]    = useState("");
  const [resending,    setResending]    = useState(false);

  const isIndividual = accountType === "individual";
  const pwStrength = strengthOf(password);

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
      const res = await fetch(`${API_BASE}/auth/signup`, {
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
      // Account created but unverified — no session issued. Show a "check your
      // email" confirmation; in dev the backend returns the link directly.
      setDevVerifyUrl(data?.verification_url ?? null);
      setSent(true);
    } catch {
      setError("Cannot reach server. Make sure the backend is running.");
    } finally {
      setLoading(false);
    }
  };

  const handleResend = async () => {
    setResending(true); setResendMsg("");
    try {
      const res = await fetch(`${API_BASE}/auth/resend-verification`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      const data = await res.json().catch(() => null);
      setResendMsg(data?.message ?? "If that account is unverified, a new link has been sent.");
    } catch {
      setResendMsg("Cannot reach server. Make sure the backend is running.");
    } finally {
      setResending(false);
    }
  };

  const field =
    "peer w-full rounded-xl border border-slate-200 bg-white py-2.5 pl-10 pr-4 text-sm text-slate-900 shadow-sm outline-none transition-all duration-200 placeholder:text-slate-400 hover:border-slate-300 focus:border-blue-500 focus:ring-4 focus:ring-blue-500/12";
  const bad = "border-red-300 focus:border-red-400 focus:ring-red-500/12";
  const icon =
    "pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400 transition-colors peer-focus:text-blue-600";

  // ── post-signup: verification email sent ─────────────────────────────────
  if (sent) {
    return (
      <div className="animate-scale-in text-center sm:text-left">
        <div className="relative mx-auto mb-6 grid h-16 w-16 place-items-center sm:mx-0">
          <span className="animate-pulse-ring absolute inset-0 rounded-full bg-blue-400/40" />
          <span className="relative grid h-16 w-16 place-items-center rounded-full bg-blue-50 ring-1 ring-blue-200">
            <MailCheck className="h-8 w-8 text-blue-600" />
          </span>
        </div>

        <h1 className="text-[1.75rem] font-bold tracking-tight text-slate-900">Check your email</h1>
        <p className="mt-2 text-sm leading-relaxed text-slate-500">
          We&apos;ve sent a verification link to{" "}
          <span className="font-semibold text-slate-700">{email}</span>. Click it to
          activate your account, then sign in.
        </p>

        {devVerifyUrl && (
          <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-left">
            <p className="mb-1.5 text-[11px] font-semibold text-amber-700">
              Developer mode — verify directly:
            </p>
            <a
              href={devVerifyUrl}
              className="break-all text-[11px] font-semibold text-blue-600 underline underline-offset-2"
            >
              Open verification link
            </a>
          </div>
        )}

        <div className="mt-7 space-y-3">
          <Link
            href="/login"
            className="group flex w-full items-center justify-center gap-2 rounded-xl py-3 text-sm font-semibold text-white shadow-lg shadow-blue-500/25 transition-all hover:-translate-y-0.5 hover:shadow-xl hover:shadow-blue-500/35"
            style={{ background: "var(--brand-grad)" }}
          >
            Go to sign in
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
          </Link>
          <button
            onClick={handleResend}
            disabled={resending}
            className="w-full rounded-xl border border-slate-200 py-3 text-sm font-semibold text-slate-700 transition-colors hover:bg-slate-50 disabled:opacity-60"
          >
            {resending ? "Sending…" : "Resend verification email"}
          </button>
          {resendMsg && (
            <p className="text-center text-[11px] text-slate-600">{resendMsg}</p>
          )}
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="animate-fade-up">
        <h1 className="text-[1.75rem] font-bold tracking-tight text-slate-900">
          Create your account
        </h1>
        <p className="mt-1.5 text-sm text-slate-500">
          {isIndividual
            ? "Set up your personal workspace — private to you."
            : "Set up your company workspace — you'll be the admin."}
        </p>
      </div>

      {/* account-type segmented toggle */}
      <div
        className="animate-fade-up mt-6 grid grid-cols-2 gap-2 rounded-2xl bg-slate-100 p-1.5"
        style={{ animationDelay: "60ms" }}
        role="tablist"
      >
        {([
          { t: "corporate" as const,  label: "Corporate",  sub: "Work email",     Icon: Building2 },
          { t: "individual" as const, label: "Individual", sub: "Personal email", Icon: User },
        ]).map(({ t, label, sub, Icon }) => {
          const active = accountType === t;
          return (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => switchType(t)}
              className={`flex flex-col items-start gap-0.5 rounded-xl px-3.5 py-2.5 text-left transition-all duration-300 ${
                active
                  ? "bg-white shadow-md shadow-slate-900/5 ring-1 ring-slate-200"
                  : "text-slate-500 hover:bg-white/60"
              }`}
            >
              <span
                className={`flex items-center gap-1.5 text-sm font-semibold ${
                  active ? "text-blue-700" : "text-slate-600"
                }`}
              >
                <Icon className="h-4 w-4" /> {label}
              </span>
              <span className={`text-[11px] ${active ? "text-slate-500" : "text-slate-400"}`}>
                {sub}
              </span>
            </button>
          );
        })}
      </div>

      {/* context banner */}
      <div
        className="animate-fade-up mt-4"
        style={{ animationDelay: "110ms" }}
        key={accountType}
      >
        {isIndividual ? (
          <div className="flex items-start gap-2.5 rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-2.5">
            <User className="mt-0.5 h-4 w-4 shrink-0 text-slate-500" />
            <p className="text-[11px] leading-snug text-slate-600">
              <span className="font-semibold">Private workspace.</span> Only you have
              access. Any email works, including Gmail or Yahoo.
            </p>
          </div>
        ) : (
          <div className="flex items-start gap-2.5 rounded-xl border border-blue-200 bg-blue-50 px-3.5 py-2.5">
            <Building2 className="mt-0.5 h-4 w-4 shrink-0 text-blue-500" />
            <p className="text-[11px] leading-snug text-blue-700">
              <span className="font-semibold">One admin per company.</span> The first
              person from your work domain becomes the admin. Teammates are added later
              from User Management.
            </p>
          </div>
        )}
      </div>

      <form onSubmit={handleSignup} className="mt-5 space-y-4" noValidate>
        {/* full name */}
        <div>
          <label htmlFor="fullName" className="mb-1.5 block text-xs font-semibold text-slate-700">
            Full name <span className="text-red-500">*</span>
          </label>
          <div className="relative">
            <input
              id="fullName"
              type="text"
              autoComplete="name"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="e.g. Rajesh Kumar"
              className={field}
            />
            <User className={icon} />
          </div>
        </div>

        {/* email */}
        <div>
          <label htmlFor="email" className="mb-1.5 block text-xs font-semibold text-slate-700">
            {isIndividual ? "Email" : "Work email"} <span className="text-red-500">*</span>
          </label>
          <div className="relative">
            <input
              id="email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => handleEmailChange(e.target.value)}
              placeholder={isIndividual ? "you@example.com" : "you@yourcompany.com"}
              className={`${field} ${!isIndividual && publicWarn ? bad : ""}`}
            />
            <Mail className={icon} />
          </div>
          {!isIndividual && domainNote && (
            <p className="animate-fade-in mt-1.5 flex items-center gap-1.5 text-[11px] font-medium text-emerald-600">
              <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
              {domainNote}
            </p>
          )}
          {!isIndividual && publicWarn && (
            <p className="animate-fade-in mt-1.5 flex items-center gap-1.5 text-[11px] font-medium text-amber-600">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
              {publicWarn}
            </p>
          )}
        </div>

        {/* company name — corporate only */}
        {!isIndividual && (
          <div className="animate-fade-up">
            <label htmlFor="company" className="mb-1.5 block text-xs font-semibold text-slate-700">
              Company name <span className="font-normal text-slate-400">(optional)</span>
            </label>
            <div className="relative">
              <input
                id="company"
                type="text"
                autoComplete="organization"
                value={companyName}
                onChange={(e) => setCompanyName(e.target.value)}
                placeholder="e.g. Yatra Online Pvt Ltd"
                className={field}
              />
              <Building2 className={icon} />
            </div>
          </div>
        )}

        {/* PAN — required for individual, optional for corporate */}
        <div>
          <label htmlFor="pan" className="mb-1.5 block text-xs font-semibold text-slate-700">
            PAN number{" "}
            {isIndividual ? (
              <span className="text-red-500">*</span>
            ) : (
              <span className="font-normal text-slate-400">(optional)</span>
            )}
          </label>
          <div className="relative">
            <input
              id="pan"
              type="text"
              value={pan}
              onChange={(e) => handlePanChange(e.target.value)}
              placeholder="ABCDE1234F"
              maxLength={10}
              className={`${field} font-mono uppercase tracking-wider ${panError ? bad : ""}`}
            />
            <CreditCard className={icon} />
          </div>
          {panError && <p className="mt-1 text-[11px] text-red-500">{panError}</p>}
        </div>

        {/* GST registered toggle */}
        <div className="rounded-xl border border-slate-200 bg-slate-50/60 px-3.5 py-3">
          <label className="flex cursor-pointer select-none items-center gap-2.5">
            <input
              type="checkbox"
              checked={gstRegistered}
              onChange={(e) => {
                setGstRegistered(e.target.checked);
                if (!e.target.checked) { setGst(""); setGstError(""); }
              }}
              className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500/30"
            />
            <span className="flex items-center gap-1.5 text-xs font-semibold text-slate-700">
              <ReceiptText className="h-3.5 w-3.5 text-slate-400" />
              Are you GST registered?
            </span>
          </label>
          {gstRegistered && (
            <div className="animate-fade-up mt-3">
              <input
                type="text"
                value={gst}
                onChange={(e) => handleGstChange(e.target.value)}
                placeholder="GSTIN — e.g. 22ABCDE1234F1Z5"
                maxLength={15}
                className={`w-full rounded-xl border border-slate-200 bg-white px-4 py-2.5 font-mono text-sm uppercase tracking-wider shadow-sm outline-none transition-all placeholder:font-sans placeholder:tracking-normal placeholder:text-slate-400 focus:border-blue-500 focus:ring-4 focus:ring-blue-500/12 ${
                  gstError ? bad : ""
                }`}
              />
              {gstError && <p className="mt-1 text-[11px] text-red-500">{gstError}</p>}
            </div>
          )}
        </div>

        {/* password */}
        <div>
          <label htmlFor="password" className="mb-1.5 block text-xs font-semibold text-slate-700">
            Password <span className="text-red-500">*</span>
          </label>
          <div className="relative">
            <input
              id="password"
              type={showPw ? "text" : "password"}
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Min 8 characters"
              className={`${field} pr-11`}
            />
            <Lock className={icon} />
            <button
              type="button"
              onClick={() => setShowPw((s) => !s)}
              aria-label={showPw ? "Hide password" : "Show password"}
              className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
            >
              {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>

          {/* strength meter */}
          {password && (
            <div className="animate-fade-in mt-2 flex items-center gap-2">
              <div className="flex flex-1 gap-1">
                {[0, 1, 2, 3].map((i) => (
                  <span
                    key={i}
                    className={`h-1 flex-1 rounded-full transition-all duration-300 ${
                      i < pwStrength.score ? pwStrength.tone.split(" ")[0] : "bg-slate-200"
                    }`}
                  />
                ))}
              </div>
              <span className={`text-[10px] font-semibold ${pwStrength.tone.split(" ")[1]}`}>
                {pwStrength.label}
              </span>
            </div>
          )}
        </div>

        {/* confirm */}
        <div>
          <label htmlFor="confirm" className="mb-1.5 block text-xs font-semibold text-slate-700">
            Confirm password <span className="text-red-500">*</span>
          </label>
          <div className="relative">
            <input
              id="confirm"
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              placeholder="Re-enter your password"
              className={`${field} ${confirm && confirm !== password ? bad : ""} ${
                confirm && confirm === password ? "border-emerald-300 focus:border-emerald-400 focus:ring-emerald-500/12" : ""
              }`}
            />
            <Lock className={icon} />
            {confirm && confirm === password && (
              <CheckCircle2 className="animate-scale-in absolute right-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-emerald-500" />
            )}
          </div>
          {confirm && confirm !== password && (
            <p className="mt-1 text-[11px] text-red-500">Passwords do not match</p>
          )}
        </div>

        {/* error */}
        {error && (
          <div className="animate-shake flex items-start gap-2.5 rounded-xl border border-red-200 bg-red-50 px-3.5 py-3">
            <TriangleAlert className="mt-px h-4 w-4 shrink-0 text-red-500" />
            <p className="text-xs leading-relaxed text-red-700">{error}</p>
          </div>
        )}

        {/* submit */}
        <button
          type="submit"
          disabled={loading}
          className="group flex w-full items-center justify-center gap-2 rounded-xl py-3.5 text-sm font-semibold text-white shadow-lg shadow-blue-500/25 transition-all hover:-translate-y-0.5 hover:shadow-xl hover:shadow-blue-500/35 disabled:translate-y-0 disabled:opacity-60 disabled:shadow-none"
          style={{ background: "var(--brand-grad)" }}
        >
          {loading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Creating account…
            </>
          ) : (
            <>
              Create account
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
            </>
          )}
        </button>
      </form>

      <p className="mt-6 text-center text-sm text-slate-600">
        Already have an account?{" "}
        <Link href="/login" className="font-semibold text-blue-600 hover:underline">
          Sign in
        </Link>
      </p>
    </div>
  );
}
