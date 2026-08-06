"use client";

import { Plus, Trash2 } from "lucide-react";
import TicketFieldInput from "./TicketFieldInput";
import {
  LEG_SECTOR_RE, MAX_LEGS, coerceFieldValue, fieldByKey, legFieldKeys,
  type ItineraryLeg, type StatementType,
} from "@/lib/ticketFields";

/** Mirror of _INDIA_AIRPORTS in backend/app/services/ticket_extraction.py. */
const INDIA_AIRPORTS = new Set([
  "DEL", "BOM", "MAA", "CCU", "HYD", "BLR", "AMD", "COK", "GOI", "JAI",
  "PNQ", "ATQ", "IXC", "LKO", "IXB", "GAU", "BBI", "IXR", "SXR", "VNS",
  "IXZ", "TRV", "IXM", "IDR", "RPR", "NAG", "VTZ", "BHO", "UDR", "JDH",
  "PAT", "GWL", "IXA", "IXE", "MYQ", "STV", "DIU", "RAJ", "IXU",
]);

/**
 * Mirror of _detect_segment_type_from_sector, for showing the user what the
 * server will fill in. Display only — a derived value is never posted, because
 * posting it would make it indistinguishable from a deliberate choice.
 */
function predictSegmentType(sector: string): "Domestic" | "International" | null {
  const [origin, dest] = sector.trim().toUpperCase().split("/");
  if (!origin || !dest) return null;
  return INDIA_AIRPORTS.has(origin) && INDIA_AIRPORTS.has(dest) ? "Domestic" : "International";
}

/**
 * Repeatable itinerary editor — one block per flown leg.
 *
 * Each leg is saved as its own ticket row with the fare divided, so this is not
 * cosmetic grouping: adding a block changes how many rows land in the statement.
 * `LegPreview` underneath shows that consequence against the server's own answer.
 *
 * Inputs are rendered from the TICKET_FIELDS catalog rather than hand-written,
 * so labels, hints and the Domestic/International options stay single-sourced.
 */
export default function ItineraryLegsEditor({
  legs, statementType, onChange, showErrors,
}: {
  legs: ItineraryLeg[];
  statementType: StatementType;
  onChange: (legs: ItineraryLeg[]) => void;
  /** Set once Save has been attempted — until then, blanks are not failures. */
  showErrors?: boolean;
}) {
  const keys = legFieldKeys(statementType);

  const set = (i: number, key: string, value: unknown) =>
    onChange(legs.map((l, j) => (j === i ? { ...l, [key]: value } : l)));

  const remove = (i: number) => onChange(legs.filter((_, j) => j !== i));

  return (
    <div className="space-y-3">
      {legs.map((leg, i) => {
        const sector = (leg.sector ?? "").trim().toUpperCase();
        const malformed = sector !== "" && !LEG_SECTOR_RE.test(sector);
        // Only the first leg is required — the rest exist because the user added them.
        const missing = !!showErrors && sector === "" && i === 0;
        const predicted = !(leg.segment_type ?? "").trim() && !malformed
          ? predictSegmentType(sector)
          : null;

        return (
          <div
            key={i}
            className="rounded-lg border border-gray-200 bg-gray-50/50 px-3 py-3 relative"
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-[10px] font-bold text-indigo-600 uppercase tracking-wider">
                Sector {i + 1}
              </span>
              {legs.length > 1 && (
                <button
                  type="button"
                  onClick={() => remove(i)}
                  className="p-1 rounded text-red-400 hover:bg-red-50"
                  title="Remove this sector"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              )}
            </div>

            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-x-4 gap-y-3">
              {keys.map((key) => {
                const field = fieldByKey[key];
                if (!field) return null;
                return (
                  <TicketFieldInput
                    key={key}
                    field={field}
                    value={leg[key as keyof ItineraryLeg] ?? null}
                    required={key === "sector" && i === 0}
                    invalid={key === "sector" && (malformed || missing)}
                    onChange={(raw) =>
                      set(i, key, coerceFieldValue(field, key === "sector" ? raw.toUpperCase() : raw))
                    }
                  />
                );
              })}
            </div>

            {malformed && (
              <p className="text-[10px] text-red-500 mt-2">
                One leg per block — write it as DEL/BOM. Add another block for the next sector.
              </p>
            )}
            {predicted && (
              <p className="text-[10px] text-gray-400 mt-2">
                Segment type will be saved as{" "}
                <span className="font-semibold text-gray-500">{predicted}</span>.
              </p>
            )}
          </div>
        );
      })}

      <button
        type="button"
        disabled={legs.length >= MAX_LEGS}
        onClick={() => onChange([...legs, {}])}
        className="flex items-center gap-1.5 text-xs text-[#1e3a5f] font-medium hover:underline disabled:text-gray-300 disabled:no-underline disabled:cursor-not-allowed"
      >
        <Plus className="w-3.5 h-3.5" /> Add sector
      </button>

      {legs.length >= MAX_LEGS && (
        <p className="text-[10px] text-gray-400">
          A ticket cannot carry more than {MAX_LEGS} sectors.
        </p>
      )}
    </div>
  );
}
