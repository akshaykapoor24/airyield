// Indian tax identifiers — PAN, GSTIN, and the state codes that tie them together.
//
// A DELIBERATE MIRROR of backend/app/core/india_tax.py. Every rule here exists
// there too, and the wording of the failures is kept close, so a form can refuse
// a bad GSTIN as it is typed and the API refuses the same value for the same
// stated reason rather than a differently phrased one. Change one, change both.
//
// WHAT A GSTIN ACTUALLY IS. Fifteen characters, and every part of it is checkable
// against something else already on the form:
//
//     2 7 A A P F U 0 9 3 9 F 1 Z V
//     ^^^ ^^^^^^^^^^^^^^^^^ ^ ^ ^
//      |         |          | | └─ check digit — mod-36 over the first fourteen
//      |         |          | └─── 'Z', fixed by the notification
//      |         |          └───── which registration this is for that PAN there
//      |         └──────────────── the holder's PAN, character for character
//      └────────────────────────── state code — 27 is Maharashtra, 07 is Delhi
//
// So a GSTIN is not an independent field: given a state and a PAN, ten of its
// fifteen characters are already determined. That is why the Add Agency form asks
// for state and PAN first and only then offers the GSTIN box.
//
// PAN HAS NO USABLE CHECK DIGIT — its tenth character is one, but the algorithm
// has never been published, so format plus the fourth-character holder type is the
// honest limit.

export const PAN_RE = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
export const GSTIN_RE = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;

// PAN's 4th character is the holder type. The BROAD assigned set on purpose — a
// PAN wrongly refused blocks the user completely, while the letters left out
// (D, I, M, N, O, Q, R, S, U, V, W, X, Y, Z) are not issued at all.
//   P individual · C company · H HUF · F firm/LLP · A AOP · T trust · B BOI
//   L local authority · J artificial juridical person · G government · E LLP · K trust
const PAN_HOLDER_TYPES = "ABCEFGHJKLPT";

/** Code → state. Current codes only; this is what the state picker offers. */
export const GST_STATE_CODES: Record<string, string> = {
  "01": "Jammu and Kashmir",
  "02": "Himachal Pradesh",
  "03": "Punjab",
  "04": "Chandigarh",
  "05": "Uttarakhand",
  "06": "Haryana",
  "07": "Delhi",
  "08": "Rajasthan",
  "09": "Uttar Pradesh",
  "10": "Bihar",
  "11": "Sikkim",
  "12": "Arunachal Pradesh",
  "13": "Nagaland",
  "14": "Manipur",
  "15": "Mizoram",
  "16": "Tripura",
  "17": "Meghalaya",
  "18": "Assam",
  "19": "West Bengal",
  "20": "Jharkhand",
  "21": "Odisha",
  "22": "Chhattisgarh",
  "23": "Madhya Pradesh",
  "24": "Gujarat",
  "26": "Dadra and Nagar Haveli and Daman and Diu",
  "27": "Maharashtra",
  "29": "Karnataka",
  "30": "Goa",
  "31": "Lakshadweep",
  "32": "Kerala",
  "33": "Tamil Nadu",
  "34": "Puducherry",
  "35": "Andaman and Nicobar Islands",
  "36": "Telangana",
  "37": "Andhra Pradesh",
  "38": "Ladakh",
  "97": "Other Territory",
};

// Retired codes that still appear on registrations issued before the change — 25
// (Daman and Diu) folded into 26 in 2020, and 28 was Andhra Pradesh before
// Telangana was carved out and new registrations moved to 37. Such a GSTIN is old,
// not wrong, so it is accepted for the state its code became.
const LEGACY_STATE_CODE_SUCCESSOR: Record<string, string> = { "25": "26", "28": "37" };

// Spellings people type or that arrive in a spreadsheet. Matching already ignores
// case and punctuation, so only genuinely different names need to be here.
const STATE_ALIASES: Record<string, string> = {
  orissa: "Odisha",
  pondicherry: "Puducherry",
  uttaranchal: "Uttarakhand",
  "new delhi": "Delhi",
  "nct of delhi": "Delhi",
  "delhi ncr": "Delhi",
  tamilnadu: "Tamil Nadu",
  "daman and diu": "Dadra and Nagar Haveli and Daman and Diu",
  "dadra and nagar haveli": "Dadra and Nagar Haveli and Daman and Diu",
  "andaman and nicobar": "Andaman and Nicobar Islands",
  jk: "Jammu and Kashmir",
};

/** What the state picker lists, and the only values the API will accept. */
export const STATE_NAMES: string[] = Object.values(GST_STATE_CODES).sort((a, b) => a.localeCompare(b));

/** "  Jammu & Kashmir " -> "jammu and kashmir". Punctuation-blind on purpose. */
function key(value: string | null | undefined): string {
  return (value ?? "")
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

const STATE_BY_KEY: Record<string, string> = {};
for (const name of Object.values(GST_STATE_CODES)) STATE_BY_KEY[key(name)] = name;
for (const [alias, name] of Object.entries(STATE_ALIASES)) STATE_BY_KEY[key(alias)] = name;

const CODE_BY_STATE: Record<string, string> = Object.fromEntries(
  Object.entries(GST_STATE_CODES).map(([code, name]) => [name, code]),
);

/** The name this state is filed under, or "" when it is not one we know. */
export function canonicalState(value: string | null | undefined): string {
  return STATE_BY_KEY[key(value)] ?? "";
}

/** "Maharashtra" -> "27". "" when the state is unrecognised. */
export function stateCode(value: string | null | undefined): string {
  return CODE_BY_STATE[canonicalState(value)] ?? "";
}

/** "  27aapfu0939f1zv " -> "27AAPFU0939F1ZV". */
export function normaliseTaxId(value: string | null | undefined): string {
  return (value ?? "").trim().toUpperCase().replace(/\s+/g, "");
}

const GST_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";

/**
 * The 15th character GSTN would have issued for these fourteen.
 *
 * Mod-36 with alternating weights 1 and 2, each weighted value folded as
 * quotient + remainder over 36. Catches every single-character typo and most
 * transpositions, which is the mistake this form has to survive.
 */
export function gstinCheckDigit(first14: string): string {
  let total = 0;
  for (let i = 0; i < first14.length; i++) {
    const weighted = GST_ALPHABET.indexOf(first14[i]) * (i % 2 ? 2 : 1);
    total += Math.floor(weighted / 36) + (weighted % 36);
  }
  return GST_ALPHABET[(36 - (total % 36)) % 36];
}

/** A readable problem with this PAN, or "" if it is fine. Blank is not a problem. */
export function panError(pan: string): string {
  if (!pan) return "";
  if (!PAN_RE.test(pan)) return "Invalid PAN — expected 10 characters, e.g. AAPFU0939F.";
  if (!PAN_HOLDER_TYPES.includes(pan[3])) {
    return `The 4th character says who holds the PAN (P individual, C company, F firm, H HUF, T trust…) — '${pan[3]}' is not one of them.`;
  }
  return "";
}

/**
 * A readable problem with this GSTIN, or "" if it is fine.
 *
 * Checks it against itself (format, check digit) and against the rest of the form
 * (state code, embedded PAN). `pan` and `state` are optional so a caller that has
 * neither yet still gets the format and checksum checks.
 */
export function gstinError(gstin: string, opts: { pan?: string; state?: string } = {}): string {
  if (!gstin) return "";
  if (!GSTIN_RE.test(gstin)) return "Invalid GSTIN — expected 15 characters, e.g. 27AAPFU0939F1ZV.";

  const code = gstin.slice(0, 2);
  const canonicalCode = LEGACY_STATE_CODE_SUCCESSOR[code] ?? code;
  if (!GST_STATE_CODES[canonicalCode]) return `'${code}' is not an Indian state code.`;

  if (opts.state) {
    const want = stateCode(opts.state);
    if (!want) return `'${opts.state}' is not a state a GSTIN can be checked against — pick one from the list.`;
    if (canonicalCode !== want) {
      return `GSTIN starts with '${code}' (${GST_STATE_CODES[canonicalCode]}) but the state is ${canonicalState(opts.state)}, whose code is '${want}'.`;
    }
  }

  if (opts.pan && gstin.slice(2, 12) !== opts.pan) {
    return `GSTIN carries PAN '${gstin.slice(2, 12)}' but the PAN field says '${opts.pan}'. Characters 3 to 12 must match it exactly.`;
  }

  const expected = gstinCheckDigit(gstin.slice(0, 14));
  if (gstin[14] !== expected) {
    return `The last character is a check digit and should be '${expected}', not '${gstin[14]}' — something earlier in it is mistyped.`;
  }
  return "";
}

// ── while the user is still typing ─────────────────────────────────────────
// panError / gstinError above are the SUBMIT-TIME checks and are right to reject
// a half-typed value. Wired straight to onChange they would put a red box under
// the field at the first keystroke and keep it there until the last one, which
// reads as "you are doing it wrong" for the entire time it is being done right.
// These two say nothing until there is something to say.

/** panError, held back until all ten characters are in. */
export function panTypingError(pan: string): string {
  return pan.length < 10 ? "" : panError(pan);
}

/**
 * gstinError, held back until all fifteen characters are in — EXCEPT the state
 * prefix, which is knowable after two and is the mistake worth catching early:
 * a Delhi GSTIN typed against a Maharashtra agency is usually the wrong number
 * entirely, not a typo, and thirteen more characters will not fix it.
 */
export function gstinTypingError(gstin: string, opts: { pan?: string; state?: string } = {}): string {
  if (gstin.length >= 2 && opts.state) {
    const want = stateCode(opts.state);
    const code = gstin.slice(0, 2);
    const canonicalCode = LEGACY_STATE_CODE_SUCCESSOR[code] ?? code;
    if (want && GST_STATE_CODES[canonicalCode] && canonicalCode !== want) {
      return `GSTIN starts with '${code}' (${GST_STATE_CODES[canonicalCode]}) but the state is ${canonicalState(opts.state)}, whose code is '${want}'.`;
    }
  }
  return gstin.length < 15 ? "" : gstinError(gstin, opts);
}

/**
 * An example GSTIN for this state and PAN, check digit and all.
 *
 * Used as the GSTIN box's placeholder so the shape being asked for is the shape
 * this particular agency's number will have — a generic example cannot show that
 * the first two characters are already decided by the state above it.
 */
export function gstinPlaceholder(state: string, pan: string): string {
  const code = stateCode(state) || "27";
  const body = PAN_RE.test(pan) ? pan : "AAPFU0939F";
  const first14 = `${code}${body}1Z`;
  return `${first14}${gstinCheckDigit(first14)}`;
}
