"use client";

import { useState } from "react";
import { AlertTriangle, BadgeCheck, MailWarning, Send } from "lucide-react";
import api from "@/lib/api";
import { ModalShell, apiError } from "@/components/userMaster/shared";

/**
 * Subscriptions → Verified. An unverified owner cannot sign in at all, so this is the
 * column that explains "they signed up but never came back". Shapes mirror
 * backend/app/schemas/subscription.py; the rules are in
 * backend/app/services/workspace_verification.py.
 */
export type VerificationState = {
  status: "verified" | "unverified" | "no_users";
  unverified_emails: string[];
  verified_at: string | null;
  /** The platform admin who verified by hand; null when the emailed link did it. */
  verified_by: string | null;
};

function fmtDateTime(v: string | null): string {
  if (!v) return "";
  // The API sends naive UTC.
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(v) ? v : `${v}Z`);
  return d.toLocaleString(undefined, { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function verifiedTitle(v: VerificationState): string {
  if (v.verified_by) return `Verified by hand by ${v.verified_by}${v.verified_at ? ` on ${fmtDateTime(v.verified_at)}` : ""}`;
  if (v.verified_at) return `Verified through the email link on ${fmtDateTime(v.verified_at)}`;
  return "Verified";
}

export function VerificationCell({ state, onVerify }: {
  state: VerificationState | null;
  onVerify: () => void;
}) {
  if (!state || state.status === "no_users") {
    return <td className="px-4 py-3 text-xs text-gray-300">—</td>;
  }
  if (state.status === "verified") {
    return (
      <td className="px-4 py-3">
        <span
          title={verifiedTitle(state)}
          className="inline-flex items-center gap-1 whitespace-nowrap px-2 py-0.5 rounded-full text-[10px] font-medium border bg-green-50 text-green-700 border-green-200 cursor-default"
        >
          <BadgeCheck className="w-3 h-3" /> Verified
        </span>
        {/* A skipped mailbox check is visible at a glance, not only on hover. */}
        {state.verified_by && <p className="mt-1 text-[10px] text-gray-400 whitespace-nowrap">by admin</p>}
      </td>
    );
  }
  return (
    <td className="px-4 py-3">
      <span
        title={`Waiting for ${state.unverified_emails.join(", ")} to click the verification link. They can't sign in until then.`}
        className="inline-flex items-center gap-1 whitespace-nowrap px-2 py-0.5 rounded-full text-[10px] font-medium border bg-amber-50 text-amber-700 border-amber-200 cursor-default"
      >
        <MailWarning className="w-3 h-3" /> Unverified
      </span>
      <button
        onClick={onVerify}
        className="block mt-1 whitespace-nowrap text-[11px] font-medium text-violet-700 hover:text-violet-900 hover:underline"
      >
        Verify…
      </button>
    </td>
  );
}

/**
 * Verify by hand, or resend the link. Verifying skips the proof that the person owns the
 * mailbox, so the dialog says so and names exactly who is affected; the server records
 * which admin did it.
 */
export function VerifyEmailModal({ tenantId, workspaceName, emails, onClose, onDone }: {
  tenantId: number;
  workspaceName: string;
  emails: string[];
  onClose: () => void;
  /** `message` is shown on the page once the dialog has closed. */
  onDone: (message: string) => void;
}) {
  const [busy, setBusy] = useState<"verify" | "resend" | null>(null);
  const [error, setError] = useState("");
  const who = emails.join(", ");

  const verify = async () => {
    setBusy("verify");
    setError("");
    try {
      await api.post(`/subscriptions/${tenantId}/verify`);
      onDone(`${who} ${emails.length === 1 ? "is" : "are"} verified and can sign in now.`);
    } catch (e) {
      setError(apiError(e));
      setBusy(null);
    }
  };

  const resend = async () => {
    setBusy("resend");
    setError("");
    try {
      const { data } = await api.post<{ sent_to: string[] }>(`/subscriptions/${tenantId}/resend-verification`);
      onDone(`A new verification link was sent to ${data.sent_to.join(", ")}.`);
    } catch (e) {
      setError(apiError(e));
      setBusy(null);
    }
  };

  return (
    <ModalShell title={`Verify email — ${workspaceName}`} onClose={onClose}>
      <div className="space-y-4">
        <div>
          <p className="text-xs text-gray-600">
            {/* One string: JSX whitespace around the expressions was being dropped. */}
            {emails.length === 1
              ? "This account hasn't confirmed its email yet, so it can't sign in:"
              : "These accounts haven't confirmed their email yet, so they can't sign in:"}
          </p>
          <ul className="mt-2 space-y-1">
            {emails.map((e) => (
              <li key={e} className="text-xs font-semibold text-gray-900 bg-gray-50 border border-gray-100 rounded-md px-2.5 py-1.5">{e}</li>
            ))}
          </ul>
        </div>

        <div className="flex gap-2 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2.5">
          <AlertTriangle className="w-3.5 h-3.5 text-amber-600 shrink-0 mt-0.5" />
          <p className="text-[11px] leading-relaxed text-amber-800">
            Verifying by hand skips the check that they own this mailbox. Do it only when you&apos;re sure
            of the address — for example, they wrote to you from it. It&apos;s recorded against your name.
            Otherwise, send them a fresh link.
          </p>
        </div>

        {error && <p className="text-[11px] text-red-500">{error}</p>}

        <div className="flex gap-2">
          <button
            onClick={resend}
            disabled={busy !== null}
            className="flex-1 inline-flex items-center justify-center gap-1.5 border border-gray-200 text-gray-700 rounded-lg py-2 text-sm font-medium hover:bg-gray-50 disabled:opacity-50"
          >
            <Send className="w-3.5 h-3.5" /> {busy === "resend" ? "Sending…" : "Resend link"}
          </button>
          <button
            onClick={verify}
            disabled={busy !== null}
            className="flex-1 inline-flex items-center justify-center gap-1.5 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50"
            style={{ background: "linear-gradient(135deg, #7c3aed, #6d28d9)" }}
          >
            <BadgeCheck className="w-3.5 h-3.5" /> {busy === "verify" ? "Verifying…" : "Mark as verified"}
          </button>
        </div>
      </div>
    </ModalShell>
  );
}
