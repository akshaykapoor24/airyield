"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { ArrowRight, CheckCircle2, Loader2, ShieldCheck, TriangleAlert, XCircle } from "lucide-react";
import api from "@/lib/api";
import { clearAuth } from "@/lib/auth";
import { apiError } from "@/components/userMaster/shared";
import PasswordField from "@/components/ui/PasswordField";
import { passwordProblem, MIN_PASSWORD_LENGTH, MAX_PASSWORD_BYTES } from "@/lib/password";

function ResetPasswordInner() {
  const router = useRouter();
  const params = useSearchParams();

  // Capture ONCE, lazily. The effect below strips ?token= from the URL, which
  // re-renders — after that params.get("token") is null, so reading it inline
  // would evaporate the token out from under the form mid-session.
  const [token] = useState(() => params.get("token"));

  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  useEffect(() => {
    // Get the token out of the address bar immediately: it is a bearer
    // credential, and leaving it there puts it in Referer headers, browser
    // history, bookmarks and cross-device history sync.
    if (token) router.replace("/reset-password", { scroll: false });
    // Intentionally once-only — `token` is captured and never changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (saving) return;
    setError("");
    const problem = passwordProblem(next);
    if (problem) { setError(problem); return; }
    if (next !== confirm) { setError("The passwords do not match."); return; }

    setSaving(true);
    try {
      await api.post("/auth/reset-password", { token, new_password: next });
      setNext(""); setConfirm("");
      // Every session was revoked server-side, including any in this browser.
      clearAuth();
      setDone(true);
    } catch (err) {
      setError(apiError(err));
    } finally {
      setSaving(false);
    }
  };

  if (!token) {
    return (
      <div className="py-4 text-center">
        <div className="mx-auto mb-4 grid h-14 w-14 place-items-center rounded-full bg-red-50">
          <XCircle className="h-8 w-8 text-red-500" />
        </div>
        <h1 className="text-2xl font-bold text-slate-900">Reset link missing</h1>
        <p className="mt-1.5 text-sm text-slate-500">
          This page needs a reset link from your email. Request a fresh one below.
        </p>
        <Link
          href="/forgot-password"
          className="mt-6 flex w-full items-center justify-center gap-2 rounded-xl py-3 text-sm font-semibold text-white shadow-lg shadow-blue-500/25 transition-all hover:-translate-y-0.5"
          style={{ background: "var(--brand-grad)" }}
        >
          Request a reset link <ArrowRight className="h-4 w-4" />
        </Link>
        <p className="mt-6 text-center text-sm text-slate-600">
          <Link href="/login" className="font-semibold text-blue-600 hover:underline">Back to sign in</Link>
        </p>
      </div>
    );
  }

  if (done) {
    return (
      <div className="animate-scale-in py-4 text-center">
        <div className="mx-auto mb-4 grid h-14 w-14 place-items-center rounded-full bg-green-50">
          <CheckCircle2 className="h-8 w-8 text-green-500" />
        </div>
        <h1 className="text-2xl font-bold text-slate-900">Password updated</h1>
        <p className="mt-1.5 text-sm text-slate-500">
          Sign in with your new password. For your security, you&apos;ve been signed out everywhere else.
        </p>
        <Link
          href="/login"
          className="group mt-6 flex w-full items-center justify-center gap-2 rounded-xl py-3 text-sm font-semibold text-white shadow-lg shadow-blue-500/25 transition-all hover:-translate-y-0.5"
          style={{ background: "var(--brand-grad)" }}
        >
          Continue to sign in
          <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
        </Link>
      </div>
    );
  }

  return (
    <div>
      <div className="animate-fade-up">
        <h1 className="text-[1.75rem] font-bold tracking-tight text-slate-900">Choose a new password</h1>
        <p className="mt-1.5 text-sm text-slate-500">
          Pick something you haven&apos;t used before. This link works only once.
        </p>
      </div>

      <div className="mt-5 flex items-start gap-2.5 rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-2.5">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-slate-500" />
        <p className="text-[11px] leading-snug text-slate-600">
          At least {MIN_PASSWORD_LENGTH} characters and at most {MAX_PASSWORD_BYTES} bytes, using
          three of: lowercase, uppercase, numbers, symbols.
        </p>
      </div>

      <form onSubmit={submit} className="mt-5 space-y-4" noValidate>
        <PasswordField
          id="new-password" label="New password" required showStrength
          autoComplete="new-password" placeholder="Min 8 characters"
          value={next} onChange={setNext} disabled={saving}
        />
        <PasswordField
          id="confirm-password" label="Confirm new password" required
          autoComplete="new-password" placeholder="Re-enter your password"
          matchValue={next} value={confirm} onChange={setConfirm} disabled={saving}
        />

        {error && (
          <div className="animate-shake flex items-start gap-2.5 rounded-xl border border-red-200 bg-red-50 px-3.5 py-3">
            <TriangleAlert className="mt-px h-4 w-4 shrink-0 text-red-500" />
            <div className="min-w-0">
              <p className="text-xs leading-relaxed text-red-700">{error}</p>
              {error.toLowerCase().includes("invalid or has expired") && (
                <Link href="/forgot-password" className="mt-1 inline-block text-xs font-semibold text-blue-600 underline underline-offset-2">
                  Request a new link
                </Link>
              )}
            </div>
          </div>
        )}

        <button
          type="submit" disabled={saving}
          className="group flex w-full items-center justify-center gap-2 rounded-xl py-3.5 text-sm font-semibold text-white shadow-lg shadow-blue-500/25 transition-all hover:-translate-y-0.5 disabled:translate-y-0 disabled:opacity-60"
          style={{ background: "var(--brand-grad)" }}
        >
          {saving ? (
            <><Loader2 className="h-4 w-4 animate-spin" /> Updating…</>
          ) : (
            <>Update password <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" /></>
          )}
        </button>
      </form>

      <p className="mt-7 text-center text-sm text-slate-600">
        <Link href="/login" className="font-semibold text-blue-600 hover:underline">Back to sign in</Link>
      </p>
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<div className="py-8 text-center text-sm text-slate-500">Loading…</div>}>
      <ResetPasswordInner />
    </Suspense>
  );
}
