"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { CheckCircle2, XCircle, Loader2, MailCheck, Send } from "lucide-react";
import api from "@/lib/api";
import { setToken, setUser } from "@/lib/auth";
import { apiError } from "@/components/userMaster/shared";

const BTN = "linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)";

function VerifyEmailInner() {
  const router = useRouter();
  const params = useSearchParams();
  const token = params.get("token");
  const ran = useRef(false);

  const [status, setStatus] = useState<"verifying" | "success" | "error">("verifying");
  const [message, setMessage] = useState("");

  // resend
  const [resendEmail, setResendEmail] = useState("");
  const [resendMsg, setResendMsg] = useState("");
  const [resending, setResending] = useState(false);

  useEffect(() => {
    if (ran.current) return;   // guard React StrictMode double-invoke
    ran.current = true;
    if (!token) { setStatus("error"); setMessage("This verification link is missing its token."); return; }
    (async () => {
      try {
        const { data } = await api.post("/auth/verify-email", { token });
        setToken(data.access_token);
        setUser(data.user);
        setStatus("success");
      } catch (e) {
        setStatus("error");
        setMessage(apiError(e));
      }
    })();
  }, [token]);

  const resend = async () => {
    if (!resendEmail) { setResendMsg("Enter your email first."); return; }
    setResending(true); setResendMsg("");
    try {
      const { data } = await api.post("/auth/resend-verification", { email: resendEmail });
      setResendMsg(data?.message ?? "If that account exists and is unverified, a new link has been sent.");
    } catch (e) {
      setResendMsg(apiError(e));
    } finally { setResending(false); }
  };

  return (
    <div className="w-full max-w-md">
      <div className="lg:hidden flex items-center gap-2.5 mb-8">
        <div className="w-9 h-9 rounded-xl flex items-center justify-center shadow-md shadow-blue-500/30" style={{ background: BTN }}>
          <Send className="w-4 h-4 text-white" />
        </div>
        <span className="font-bold text-lg tracking-tight">
          <span className="text-slate-800">Fare</span><span className="text-orange-500">Qube</span>
        </span>
      </div>

      {status === "verifying" && (
        <div className="text-center py-8">
          <Loader2 className="w-10 h-10 text-blue-600 animate-spin mx-auto mb-4" />
          <h1 className="text-xl font-bold text-slate-900">Verifying your email…</h1>
          <p className="text-sm text-slate-500 mt-1">Just a moment.</p>
        </div>
      )}

      {status === "success" && (
        <div className="text-center py-4">
          <div className="w-14 h-14 rounded-full bg-green-50 flex items-center justify-center mx-auto mb-4">
            <CheckCircle2 className="w-8 h-8 text-green-500" />
          </div>
          <h1 className="text-2xl font-bold text-slate-900">Email verified!</h1>
          <p className="text-sm text-slate-500 mt-1.5">Your account is now active. Let&apos;s finish setting up your workspace.</p>
          <button
            onClick={() => router.push("/dashboard")}
            className="w-full text-white py-3 rounded-xl font-semibold text-sm hover:opacity-90 transition-all mt-6 shadow-md shadow-blue-500/25"
            style={{ background: BTN }}>
            Continue to FareQube
          </button>
        </div>
      )}

      {status === "error" && (
        <div className="py-4">
          <div className="text-center">
            <div className="w-14 h-14 rounded-full bg-red-50 flex items-center justify-center mx-auto mb-4">
              <XCircle className="w-8 h-8 text-red-500" />
            </div>
            <h1 className="text-2xl font-bold text-slate-900">Verification failed</h1>
            <p className="text-sm text-slate-500 mt-1.5">{message || "This link is invalid or has expired."}</p>
          </div>

          <div className="mt-6 bg-slate-50 border border-slate-200 rounded-xl p-4">
            <p className="flex items-center gap-1.5 text-xs font-semibold text-slate-700 mb-2">
              <MailCheck className="w-4 h-4 text-slate-400" /> Request a new link
            </p>
            <input
              type="email"
              value={resendEmail}
              onChange={e => setResendEmail(e.target.value)}
              placeholder="you@company.com"
              className="w-full border border-slate-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400 transition-colors" />
            {resendMsg && <p className="text-[11px] text-slate-600 mt-2">{resendMsg}</p>}
            <button
              onClick={resend}
              disabled={resending}
              className="w-full text-white py-2.5 rounded-xl font-semibold text-sm hover:opacity-90 disabled:opacity-60 transition-all mt-3 shadow-md shadow-blue-500/25"
              style={{ background: BTN }}>
              {resending ? "Sending…" : "Resend verification link"}
            </button>
          </div>
        </div>
      )}

      <p className="text-center text-sm text-slate-600 mt-6">
        <Link href="/login" className="font-semibold text-blue-600 hover:underline">Back to sign in</Link>
      </p>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={<div className="w-full max-w-md py-8 text-center text-sm text-slate-500">Loading…</div>}>
      <VerifyEmailInner />
    </Suspense>
  );
}
