import toast from "react-hot-toast";

/**
 * One shared way to check mandatory fields and tell the user what is missing.
 *
 * Written because the deal forms each rolled their own partial check — the New
 * Deal form validated 3 of the 5 fields its own API declares required, and the
 * Upload flow validated nothing at all before saving. Anything that slipped
 * through was accepted by the API as an empty string and stored as NULL, so the
 * user got a success toast for a deal that was quietly incomplete.
 *
 * Use it in every submit handler:
 *
 *   if (!requireFields([
 *     { label: "Airline Name", value: airlineName },
 *     { label: "Supplier Name", value: supplierName, when: dealType === "b2b" },
 *   ])) return;
 */

export type RequiredField = {
  /** Shown to the user exactly as it is labelled on screen. */
  label: string;
  value: unknown;
  /** Only enforced when true (default). Use for fields that are conditionally required. */
  when?: boolean;
};

/** Empty string, whitespace-only, null/undefined, empty array — all "not filled". */
export function isBlank(value: unknown): boolean {
  if (value === null || value === undefined) return true;
  if (typeof value === "string") return value.trim() === "";
  if (Array.isArray(value)) return value.length === 0;
  return false;
}

/** Labels of every required field that is still blank, in declaration order. */
export function missingFields(fields: RequiredField[]): string[] {
  return fields
    .filter((f) => f.when !== false)
    .filter((f) => isBlank(f.value))
    .map((f) => f.label);
}

/** Human sentence for a set of missing labels. */
export function missingMessage(missing: string[], context?: string): string {
  const where = context ? ` in ${context}` : "";
  if (missing.length === 1) return `${missing[0]} is required${where}.`;
  return `${missing.length} required fields are missing${where}: ${missing.join(", ")}.`;
}

/**
 * Check the fields; on failure raise the side notification and return false.
 * Returns true when everything is filled, so it reads as a guard clause.
 *
 * `context` is appended to the message — pass the row or tab the problem is in
 * (e.g. "row 3") so the user knows where to look on a long form.
 */
export function requireFields(fields: RequiredField[], context?: string): boolean {
  const missing = missingFields(fields);
  if (missing.length === 0) return true;
  toast.error(missingMessage(missing, context), { duration: 5000 });
  return false;
}

/** Same notification without the field-list plumbing, for one-off conditions. */
export function notifyRequired(message: string): false {
  toast.error(message, { duration: 5000 });
  return false;
}
