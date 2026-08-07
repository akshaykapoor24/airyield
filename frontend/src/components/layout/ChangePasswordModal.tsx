"use client";

import { useState } from "react";
import { CheckCircle2, ShieldCheck } from "lucide-react";
import api from "@/lib/api";
import { setToken, setUser } from "@/lib/auth";
import { useAppDispatch } from "@/store/hooks";
import { sessionRefreshed } from "@/store/slices/authSlice";
import { ModalShell, apiError } from "@/components/userMaster/shared";
import PasswordField from "@/components/ui/PasswordField";
import { passwordProblem } from "@/lib/password";

export default function ChangePasswordModal({ onClose }: { onClose: () => void }) {
  const dispatch = useAppDispatch();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (saving) return;
    setError("");

    if (!current || !next || !confirm) { setError("Please fill in all three fields."); return; }
    const problem = passwordProblem(next);
    if (problem) { setError(problem); return; }
    if (next !== confirm) { setError("The new passwords do not match."); return; }
    if (next === current) { setError("Your new password must be different from your current password."); return; }

    setSaving(true);
    try {
      const { data } = await api.post("/auth/change-password", {
        current_password: current,
        new_password: next,
      });
      // The old token is dead server-side now; adopt the fresh one so this tab
      // keeps working while every other session is signed out.
      setToken(data.access_token);
      setUser(data.user);
      dispatch(sessionRefreshed({ token: data.access_token, user: data.user }));
      // Don't leave plaintext sitting in component state.
      setCurrent(""); setNext(""); setConfirm("");
      setDone(true);
      setTimeout(onClose, 1400);
    } catch (err) {
      // Reachable as an inline message only because the API answers a wrong
      // current password with 400 — a 401 would trip the axios interceptor and
      // sign the user out mid-modal.
      setError(apiError(err));
    } finally {
      setSaving(false);
    }
  };

  if (done) {
    return (
      <ModalShell title="Change Password" onClose={onClose}>
        <div className="py-6 text-center">
          <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-full bg-green-50">
            <CheckCircle2 className="h-7 w-7 text-green-500" />
          </div>
          <p className="text-sm font-semibold text-gray-900">Password updated</p>
          <p className="mt-1 text-xs text-gray-500">
            You&apos;ve been signed out on your other devices.
          </p>
        </div>
      </ModalShell>
    );
  }

  return (
    <ModalShell title="Change Password" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-3" noValidate>
        <div className="flex items-start gap-2 rounded-lg border border-sky-100 bg-sky-50 px-3 py-2">
          <ShieldCheck className="mt-px h-3.5 w-3.5 shrink-0 text-sky-500" />
          <p className="text-[11px] leading-relaxed text-sky-800">
            Changing your password signs you out everywhere else. This device stays signed in.
          </p>
        </div>

        <PasswordField
          id="current-password" label="Current password" variant="compact" required
          autoComplete="current-password" value={current} onChange={setCurrent} disabled={saving}
        />
        <PasswordField
          id="new-password" label="New password" variant="compact" required showStrength
          autoComplete="new-password" placeholder="At least 8 characters"
          value={next} onChange={setNext} disabled={saving}
        />
        <PasswordField
          id="confirm-password" label="Confirm new password" variant="compact" required
          autoComplete="new-password" matchValue={next}
          value={confirm} onChange={setConfirm} disabled={saving}
        />

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2">
            <p className="text-[11px] leading-relaxed text-red-700">{error}</p>
          </div>
        )}

        <div className="flex gap-3 pt-1">
          <button
            type="button" onClick={onClose} disabled={saving}
            className="flex-1 rounded-lg border border-gray-200 py-2 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="submit" disabled={saving}
            className="flex-1 rounded-lg py-2 text-sm font-semibold text-white disabled:opacity-50"
            style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}
          >
            {saving ? "Updating…" : "Update password"}
          </button>
        </div>
      </form>
    </ModalShell>
  );
}
