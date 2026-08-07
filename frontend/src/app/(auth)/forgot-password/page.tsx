"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, ArrowRight, Loader2, Mail, MailCheck, TriangleAlert } from "lucide-react";
import api from "@/lib/api";
import { apiError } from "@/components/userMaster/shared";

// No useSearchParams here, so this page needs no Suspense boundary — unlike
// verify-email / reset-password. The (auth) layout already supplies the
// centred max-w-md column and the brand panel.
export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  // Mirrors the server's per-email limit so the user learns the rhythm instead
  // of walking into a 429.
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown((s) => s - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (sending || cooldown > 0) return;
    if (!email) { setError("Please enter your email address."); return; }
    setSending(true); setError("");
    try {
      const { data } = await api.post("/auth/forgot-password", { email });
      // The response is deliberately identical whether or not the account
      // exists — never branch the UI on it.
      setMessage(data?.message ?? "If an account exists for that email, we've sent a reset link.");
      setSent(true);
      setCooldown(30);
    } catch (err) {
      setError(apiError(err));
    } finally {
      setSending(false);
    }
  };

  const field =
    "peer w-full rounded-xl border border-slate-200 bg-white py-2.5 pl-10 pr-4 text-sm text-slate-900 shadow-sm outline-none transition-all duration-200 placeholder:text-slate-400 hover:border-slate-300 focus:border-blue-500 focus:ring-4 focus:ring-blue-500/12";
  const icon =
    "pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400 transition-colors peer-focus:text-blue-600";

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
        <p className="mt-2 text-sm leading-relaxed text-slate-500">{message}</p>
        <p className="mt-3 text-xs leading-relaxed text-slate-400">
          Didn&apos;t get it? Check your spam folder — the message comes from our system address.
        </p>

        <div className="mt-7 space-y-3">
          <Link
            href="/login"
            className="group flex w-full items-center justify-center gap-2 rounded-xl py-3 text-sm font-semibold text-white shadow-lg shadow-blue-500/25 transition-all hover:-translate-y-0.5"
            style={{ background: "var(--brand-grad)" }}
          >
            Back to sign in
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
          </Link>
          <button
            onClick={() => { setSent(false); setError(""); }}
            disabled={cooldown > 0}
            className="w-full rounded-xl border border-slate-200 py-3 text-sm font-semibold text-slate-700 transition-colors hover:bg-slate-50 disabled:opacity-60"
          >
            {cooldown > 0 ? `Try another email in ${cooldown}s` : "Use a different email"}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div>
      <Link
        href="/login"
        className="mb-5 inline-flex w-fit items-center gap-1.5 text-xs font-medium text-slate-400 transition-colors hover:text-slate-700"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> Back to sign in
      </Link>

      <div className="animate-fade-up">
        <h1 className="text-[1.75rem] font-bold tracking-tight text-slate-900">Forgot your password?</h1>
        <p className="mt-1.5 text-sm text-slate-500">
          Enter the email you sign in with and we&apos;ll send you a link to choose a new password.
        </p>
      </div>

      <form onSubmit={submit} className="mt-7 space-y-4" noValidate>
        <div className="animate-fade-up" style={{ animationDelay: "60ms" }}>
          <label htmlFor="email" className="mb-1.5 block text-xs font-semibold text-slate-700">
            Email address
          </label>
          <div className="relative">
            <input
              id="email" type="email" autoComplete="email" value={email}
              onChange={(e) => { setEmail(e.target.value); setError(""); }}
              placeholder="you@company.com" className={field}
            />
            <Mail className={icon} />
          </div>
        </div>

        {error && (
          <div className="animate-shake flex items-start gap-2.5 rounded-xl border border-red-200 bg-red-50 px-3.5 py-3">
            <TriangleAlert className="mt-px h-4 w-4 shrink-0 text-red-500" />
            <p className="text-xs leading-relaxed text-red-700">{error}</p>
          </div>
        )}

        <button
          type="submit" disabled={sending}
          className="group animate-fade-up flex w-full items-center justify-center gap-2 rounded-xl py-3.5 text-sm font-semibold text-white shadow-lg shadow-blue-500/25 transition-all hover:-translate-y-0.5 disabled:translate-y-0 disabled:opacity-60"
          style={{ background: "var(--brand-grad)", animationDelay: "120ms" }}
        >
          {sending ? (
            <><Loader2 className="h-4 w-4 animate-spin" /> Sending…</>
          ) : (
            <>Send reset link <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" /></>
          )}
        </button>
      </form>

      <p className="mt-7 text-center text-sm text-slate-600">
        Remembered it?{" "}
        <Link href="/login" className="font-semibold text-blue-600 hover:underline">Sign in</Link>
      </p>
    </div>
  );
}
