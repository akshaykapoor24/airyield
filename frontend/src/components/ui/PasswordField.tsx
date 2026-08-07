"use client";

import { useState } from "react";
import { CheckCircle2, Eye, EyeOff, Lock } from "lucide-react";
import { strengthOf } from "@/lib/password";

/**
 * The password input used by every password form in the app.
 *
 * Lives in components/ui/ rather than beside either caller because both the
 * (auth) pages and the dashboard's change-password modal use it — putting it in
 * one would make the other import across a feature boundary.
 *
 * `variant` carries the two visual languages the app already has: the (auth)
 * pages use tall rounded-xl fields with a 4px focus ring, the dashboard uses the
 * compact rounded-lg gray fields from userMaster/shared. Baking both in here is
 * what stops every call site re-deriving the class strings and drifting.
 */
export type PasswordFieldProps = {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete?: "current-password" | "new-password";
  placeholder?: string;
  /** Show the 4-segment strength hint under the field. */
  showStrength?: boolean;
  /** When set, renders a match tick / mismatch message against this value. */
  matchValue?: string;
  error?: string;
  required?: boolean;
  disabled?: boolean;
  variant?: "auth" | "compact";
  /** Optional right-aligned element in the label row (e.g. "Forgot password?"). */
  labelAction?: React.ReactNode;
};

export default function PasswordField({
  id,
  label,
  value,
  onChange,
  autoComplete = "new-password",
  placeholder,
  showStrength = false,
  matchValue,
  error,
  required = false,
  disabled = false,
  variant = "auth",
  labelAction,
}: PasswordFieldProps) {
  const [show, setShow] = useState(false);
  const strength = strengthOf(value);

  const isAuth = variant === "auth";
  const field = isAuth
    ? "peer w-full rounded-xl border border-slate-200 bg-white py-2.5 pl-10 pr-11 text-sm text-slate-900 shadow-sm outline-none transition-all duration-200 placeholder:text-slate-400 hover:border-slate-300 focus:border-blue-500 focus:ring-4 focus:ring-blue-500/12 disabled:opacity-60"
    : "peer w-full border border-gray-200 rounded-lg bg-gray-50 pl-9 pr-10 py-2 text-sm outline-none focus:ring-2 focus:ring-sky-400 disabled:opacity-60";
  const bad = isAuth
    ? "border-red-300 focus:border-red-400 focus:ring-red-500/12"
    : "border-red-300 focus:ring-red-300";
  const iconCls = isAuth
    ? "pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400 transition-colors peer-focus:text-blue-600"
    : "pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-gray-400";
  const labelCls = isAuth
    ? "text-xs font-semibold text-slate-700"
    : "block text-[11px] font-semibold text-gray-500 uppercase tracking-wide";

  const mismatch = matchValue !== undefined && value.length > 0 && value !== matchValue;
  const matched = matchValue !== undefined && value.length > 0 && value === matchValue;

  return (
    <div>
      <div className={`mb-1.5 flex items-center justify-between ${labelAction ? "" : "block"}`}>
        <label htmlFor={id} className={labelCls}>
          {label} {required && <span className="text-red-500">*</span>}
        </label>
        {labelAction}
      </div>
      <div className="relative">
        <input
          id={id}
          type={show ? "text" : "password"}
          autoComplete={autoComplete}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className={`${field} ${error || mismatch ? bad : ""} ${
            matched && isAuth ? "border-emerald-300 focus:border-emerald-400 focus:ring-emerald-500/12" : ""
          }`}
        />
        <Lock className={iconCls} />
        <button
          type="button"
          onClick={() => setShow((s) => !s)}
          aria-label={show ? "Hide password" : "Show password"}
          className={`absolute ${isAuth ? "right-3" : "right-2.5"} top-1/2 -translate-y-1/2 rounded-md p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600`}
        >
          {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </button>
      </div>

      {showStrength && value && (
        <div className="animate-fade-in mt-2 flex items-center gap-2">
          <div className="flex flex-1 gap-1">
            {[0, 1, 2, 3].map((i) => (
              <span
                key={i}
                className={`h-1 flex-1 rounded-full transition-all duration-300 ${
                  i < strength.score ? strength.tone.split(" ")[0] : "bg-slate-200"
                }`}
              />
            ))}
          </div>
          <span className={`text-[10px] font-semibold ${strength.tone.split(" ")[1]}`}>
            {strength.label}
          </span>
        </div>
      )}

      {matched && (
        <p className="mt-1 flex items-center gap-1 text-[11px] font-medium text-emerald-600">
          <CheckCircle2 className="h-3.5 w-3.5" /> Passwords match
        </p>
      )}
      {mismatch && <p className="mt-1 text-[11px] text-red-500">Passwords do not match</p>}
      {error && <p className="mt-1 text-[11px] text-red-500">{error}</p>}
    </div>
  );
}
