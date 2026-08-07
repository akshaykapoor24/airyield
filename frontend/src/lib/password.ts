/**
 * Client-side password helpers, shared by signup, change-password and reset.
 *
 * Advisory only — backend/app/core/password_policy.py is authoritative. What is
 * mirrored here are the two *rejection* rules, so the user is not round-tripped
 * to the server for something obvious. The strength meter is a hint and is
 * deliberately NOT a gate.
 */

export const MIN_PASSWORD_LENGTH = 8;

/**
 * bcrypt refuses anything longer, and measures in UTF-8 BYTES — one emoji is
 * four of them. Keep in sync with MAX_PASSWORD_BYTES in the backend policy.
 */
export const MAX_PASSWORD_BYTES = 72;

export function byteLength(password: string): number {
  return new TextEncoder().encode(password).length;
}

/** Advisory mirror of the server's hard rules. null = looks acceptable. */
export function passwordProblem(password: string): string | null {
  if (!password) return "Password is required.";
  if (password.length < MIN_PASSWORD_LENGTH)
    return `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
  if (byteLength(password) > MAX_PASSWORD_BYTES)
    return `Password must be at most ${MAX_PASSWORD_BYTES} bytes — shorter if you use emoji or accented letters.`;
  const classes =
    Number(/[a-z]/.test(password)) +
    Number(/[A-Z]/.test(password)) +
    Number(/\d/.test(password)) +
    Number(/[^A-Za-z0-9]/.test(password));
  if (classes < 3)
    return "Use at least three of: lowercase, uppercase, numbers, symbols.";
  return null;
}

/** Purely visual strength hint — the server enforces the real rule. */
export function strengthOf(pw: string) {
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
