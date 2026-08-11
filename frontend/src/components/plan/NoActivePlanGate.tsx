"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Lock, Mail, RefreshCw, LogOut, CheckCircle2 } from "lucide-react";
import Logo from "@/components/marketing/Logo";
import { clearPlanBlocked } from "@/lib/planGate";
import { fetchMe, logout as logoutThunk } from "@/store/slices/authSlice";
import { useAppDispatch } from "@/store/hooks";
import type { AuthUser } from "@/lib/auth";

const SUPPORT_EMAIL = "info@fareqube.com";

/**
 * Shown instead of the whole dashboard when the signed-in user's workspace has
 * no active plan. Rendered *in place of* the shell rather than layered over it,
 * so no page mounts, no request fires, and there is no 402 storm behind the
 * card.
 *
 * The backend is the real gate (402 from get_current_user); this is the part
 * that tells the user what to do about it.
 */
export default function NoActivePlanGate({ user }: { user: AuthUser | null }) {
  const dispatch = useAppDispatch();
  const router = useRouter();
  const [checking, setChecking] = useState(false);
  const [stillFrozen, setStillFrozen] = useState(false);

  const status = (user?.plan_status ?? "free") as string;
  const lapsed = status === "expired" || status === "suspended";

  const headline = lapsed ? "Your subscription has ended" : "No active plan";
  const body = lapsed
    ? "This workspace's subscription is no longer active, so the platform is paused. Get in touch and we'll get you back up and running."
    : "This workspace doesn't have an active subscription yet. Get in touch and we'll switch it on for you.";

  const mailto =
    `mailto:${SUPPORT_EMAIL}` +
    `?subject=${encodeURIComponent("Activate my FareQube workspace")}` +
    `&body=${encodeURIComponent(
      `Hi FareQube team,\n\nPlease activate our workspace.\n\n` +
        `Account: ${user?.email ?? ""}\n` +
        `Name: ${user?.full_name ?? ""}\n` +
        `Workspace: ${user?.department ?? ""}\n\nThanks.`
    )}`;

  /** Re-read /users/me. The plan is read from the database on every request, so
   *  the moment we activate the workspace this lets them straight in — no need
   *  to sign out and back in. */
  const checkAgain = async () => {
    setChecking(true);
    setStillFrozen(false);
    clearPlanBlocked();
    try {
      const fresh = await dispatch(fetchMe()).unwrap();
      if (fresh?.plan_active === false) setStillFrozen(true);
    } catch {
      setStillFrozen(true);
    } finally {
      setChecking(false);
    }
  };

  const handleLogout = async () => {
    await dispatch(logoutThunk());
    router.push("/login");
  };

  return (
    <div className="min-h-screen w-full bg-gray-50 flex flex-col items-center justify-center p-4">
      <div className="w-full max-w-lg bg-white rounded-2xl shadow-xl border border-gray-100 overflow-hidden">
        <div className="px-8 pt-8 pb-6 flex flex-col items-center text-center">
          <Logo />

          <div className="mt-7 grid h-14 w-14 place-items-center rounded-2xl bg-amber-50 border border-amber-100">
            <Lock className="h-6 w-6 text-amber-500" />
          </div>

          <h1 className="mt-5 text-xl font-bold text-slate-900">{headline}</h1>
          <p className="mt-2 text-sm leading-relaxed text-slate-500 max-w-sm">{body}</p>

          <a
            href={`mailto:${SUPPORT_EMAIL}`}
            className="mt-5 inline-flex items-center gap-2 rounded-xl border border-blue-100 bg-blue-50 px-4 py-2.5 text-sm font-semibold text-blue-700 hover:bg-blue-100 transition-colors"
          >
            <Mail className="h-4 w-4" />
            {SUPPORT_EMAIL}
          </a>

          {stillFrozen && (
            <p className="mt-4 text-[11px] text-slate-400">
              Still no active plan on this workspace. If you&apos;ve just spoken to us, give it a
              moment and try again.
            </p>
          )}
        </div>

        <div className="border-t border-gray-100 px-8 py-5 flex flex-col sm:flex-row gap-2.5">
          <a
            href={mailto}
            className="flex-1 inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold text-white shadow-sm"
            style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}
          >
            <Mail className="h-4 w-4" /> Email us
          </a>
          <button
            onClick={checkAgain}
            disabled={checking}
            className="flex-1 inline-flex items-center justify-center gap-2 rounded-xl border border-gray-200 px-4 py-2.5 text-sm font-semibold text-slate-600 hover:bg-gray-50 disabled:opacity-50"
          >
            {checking ? (
              <RefreshCw className="h-4 w-4 animate-spin" />
            ) : (
              <CheckCircle2 className="h-4 w-4" />
            )}
            {checking ? "Checking…" : "Check again"}
          </button>
          <button
            onClick={handleLogout}
            className="inline-flex items-center justify-center gap-2 rounded-xl border border-gray-200 px-4 py-2.5 text-sm font-semibold text-slate-500 hover:bg-gray-50"
          >
            <LogOut className="h-4 w-4" /> Log out
          </button>
        </div>
      </div>

      {user?.email && (
        <p className="mt-5 text-[11px] text-slate-400">Signed in as {user.email}</p>
      )}
    </div>
  );
}
