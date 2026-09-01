// The LCC airline picker's options — User Master → Airline Master, flattened to ids.
//
// An LCC Detailed export names no carrier (no airline column, bare flight numbers), so
// picking ids here is the ONLY thing that identifies the airline on an upload. A
// statement usually covers SEVERAL of the user's ids for that carrier, so the picker is
// a multi-select.
//
// But never ids from two carriers: the batch and every one of its rows carry a single
// airline_code stamped from this selection, and the file has nothing that would let a
// row be attributed to one id rather than the other. `sameAirlineOnly` is the client
// half of that rule (the server enforces it in services/lcc_airline_selection.py) —
// written once here because both LccUploadWizard (upload) and LccDetailedView (fixing a
// batch after the fact) render the same picker and must not drift apart.

/** One entry from GET /tenant-airlines/. `ref_id` is the user's own id. */
export type TenantAirlineOpt = {
  id: number;
  airline_id: number;
  ref_id: string;
  airline_name: string | null;
  airline_code: string | null;
};

/** How the carrier reads next to an id, e.g. "INDIGO (6E)". */
export const airlineLabel = (a: TenantAirlineOpt) =>
  `${a.airline_name ?? "Unknown airline"}${a.airline_code ? ` (${a.airline_code})` : ""}`;

/** MultiSelectDropdown options: the id is what the user picks, the carrier is context. */
export function toOptions(opts: TenantAirlineOpt[]) {
  return opts.map(a => ({ value: a.id, label: a.ref_id, sublabel: airlineLabel(a) }));
}

/**
 * Narrow the list to the carrier already chosen.
 *
 * Filtering rather than showing un-clickable rows: a disabled list of every other
 * airline's ids is noise, and the caller shows `lockedAirline` so the shorter list
 * never looks like missing data.
 */
export function sameAirlineOnly(
  opts: TenantAirlineOpt[], selected: number[],
): { options: TenantAirlineOpt[]; lockedAirline: string | null } {
  if (!selected.length) return { options: opts, lockedAirline: null };
  const first = opts.find(a => a.id === selected[0]);
  // The selection can name an id that is no longer in the list (deactivated since the
  // batch was uploaded). Nothing to narrow by, so leave the list whole.
  if (!first) return { options: opts, lockedAirline: null };
  return {
    options: opts.filter(a => a.airline_id === first.airline_id),
    lockedAirline: airlineLabel(first),
  };
}
