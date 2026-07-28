"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowRight, Eye, EyeOff, Loader2, Lock, Mail, TriangleAlert } from "lucide-react";
import { useAppDispatch } from "@/store/hooks";
import { login } from "@/store/slices/authSlice";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export default function LoginPage() {
  const router = useRouter();
  const dispatch = useAppDispatch();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [needsVerify, setNeedsVerify] = useState(false);
  const [resendMsg, setResendMsg] = useState("");
  const [resending, setResending] = useState(false);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(""); setNeedsVerify(false); setResendMsg("");
    if (!email || !password) { setError("Please enter email and password."); return; }
    setLoading(true);
    const result = await dispatch(login({ username: email, password }));
    setLoading(false);
    if (login.rejected.match(result)) {
      const msg = (result.payload as string) ?? "Login failed. Please try again.";
      setError(msg);
      if (msg.toLowerCase().includes("verify")) setNeedsVerify(true);
      return;
    }
    router.push("/dashboard");
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
    "peer w-full rounded-xl border border-slate-200 bg-white py-3 pl-11 pr-4 text-sm text-slate-900 shadow-sm outline-none transition-all duration-200 placeholder:text-slate-400 hover:border-slate-300 focus:border-blue-500 focus:ring-4 focus:ring-blue-500/12";
  const icon =
    "pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400 transition-colors peer-focus:text-blue-600";

  return (
    <div>
      <div className="animate-fade-up">
        <h1 className="text-[1.75rem] font-bold tracking-tight text-slate-900">Welcome back</h1>
        <p className="mt-1.5 text-sm text-slate-500">
          Sign in to pick up where your last statement left off.
        </p>
      </div>

      <form onSubmit={handleLogin} className="mt-8 space-y-4" noValidate>
        {/* email */}
        <div className="animate-fade-up" style={{ animationDelay: "60ms" }}>
          <label htmlFor="email" className="mb-1.5 block text-xs font-semibold text-slate-700">
            Email address
          </label>
          <div className="relative">
            <input
              id="email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
              className={field}
            />
            <Mail className={icon} />
          </div>
        </div>

        {/* password */}
        <div className="animate-fade-up" style={{ animationDelay: "120ms" }}>
          <div className="mb-1.5 flex items-center justify-between">
            <label htmlFor="password" className="text-xs font-semibold text-slate-700">
              Password
            </label>
            <Link href="/login" className="text-xs font-medium text-blue-600 hover:underline">
              Forgot password?
            </Link>
          </div>
          <div className="relative">
            <input
              id="password"
              type={showPw ? "text" : "password"}
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter your password"
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
        </div>

        {/* error */}
        {error && (
          <div className="animate-shake flex items-start gap-2.5 rounded-xl border border-red-200 bg-red-50 px-3.5 py-3">
            <TriangleAlert className="mt-px h-4 w-4 shrink-0 text-red-500" />
            <div className="min-w-0">
              <p className="text-xs leading-relaxed text-red-700">{error}</p>
              {needsVerify && (
                <div className="mt-2">
                  <button
                    type="button"
                    onClick={handleResend}
                    disabled={resending}
                    className="text-xs font-semibold text-blue-600 underline underline-offset-2 hover:opacity-80 disabled:opacity-60"
                  >
                    {resending ? "Sending…" : "Resend verification email"}
                  </button>
                  {resendMsg && <p className="mt-1 text-[11px] text-slate-600">{resendMsg}</p>}
                </div>
              )}
            </div>
          </div>
        )}

        {/* submit */}
        <button
          type="submit"
          disabled={loading}
          className="group animate-fade-up flex w-full items-center justify-center gap-2 rounded-xl py-3.5 text-sm font-semibold text-white shadow-lg shadow-blue-500/25 transition-all hover:-translate-y-0.5 hover:shadow-xl hover:shadow-blue-500/35 disabled:translate-y-0 disabled:opacity-60 disabled:shadow-none"
          style={{ background: "var(--brand-grad)", animationDelay: "180ms" }}
        >
          {loading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Signing in…
            </>
          ) : (
            <>
              Sign in
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
            </>
          )}
        </button>
      </form>

      <div className="my-6 flex items-center gap-3">
        <div className="h-px flex-1 bg-slate-200" />
        <span className="text-[11px] font-medium uppercase tracking-wider text-slate-400">or</span>
        <div className="h-px flex-1 bg-slate-200" />
      </div>

      <p className="text-center text-sm text-slate-600">
        New to FareQube?{" "}
        <Link href="/signup" className="font-semibold text-blue-600 hover:underline">
          Create an account
        </Link>
      </p>

      <p className="mt-7 text-center text-[11px] leading-relaxed text-slate-400">
        By signing in you agree to our Terms of Service and Privacy Policy.
      </p>
    </div>
  );
}
