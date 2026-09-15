"use client";

/**
 * What a billing line IS — Air, Hotel, Train, Bus or Car — and what to show for it.
 *
 * Billing tables were built for airline tickets: Ticket #, Airline, Sector. A hotel
 * night or a train berth from a Third Party API statement has none of those, so a
 * non-air line shows its booking reference, the property / train / operator, and its
 * route or stay in those three columns instead. The server sends that description as
 * `service_details` (backend services/tp_api_itinerary.py); this file only picks which
 * piece goes in which cell, so Customer Billing, Corporate Billing and the Third Party
 * API worklist cannot drift apart.
 */

import { MARKUP_CATEGORIES, type MarkupCategory } from "@/lib/party";

const STYLE: Record<string, string> = {
  air:   "bg-sky-50 text-sky-700 border-sky-200",
  hotel: "bg-violet-50 text-violet-700 border-violet-200",
  train: "bg-amber-50 text-amber-700 border-amber-200",
  bus:   "bg-teal-50 text-teal-700 border-teal-200",
  car:   "bg-rose-50 text-rose-700 border-rose-200",
  mice:  "bg-indigo-50 text-indigo-700 border-indigo-200",
};
const UNKNOWN_STYLE = "bg-red-50 text-red-700 border-red-200";

const LABEL: Record<string, string> = Object.fromEntries(
  MARKUP_CATEGORIES.map((c) => [c.value, c.label]),
);

/** The categories a statement line can bill under, in the order the markup form shows them. */
export const BILLABLE_CATEGORIES = MARKUP_CATEGORIES.filter((c) => c.value !== "mice");

export function categoryLabel(category: string | null | undefined): string {
  return category ? LABEL[category] ?? category : "No category";
}

export default function CategoryBadge({
  category, title, className = "",
}: { category: MarkupCategory | string | null | undefined; title?: string; className?: string }) {
  return (
    <span
      title={title}
      className={`inline-flex px-1.5 py-0.5 rounded border text-[10px] font-medium whitespace-nowrap ${
        category ? STYLE[category] ?? STYLE.air : UNKNOWN_STYLE} ${className}`}
    >
      {categoryLabel(category)}
    </span>
  );
}

/** The description the server stores on a non-air line. Absent on an air ticket. */
export type ServiceDetails = {
  category?: string;
  label?: string;
  /** The property, train or operator — shown where the airline would be. */
  title?: string;
  /** The route or city — shown where the sector would be. */
  route?: string;
  /** One readable line: "Trident Chennai · Chennai · 23 Sep → 27 Sep 2026 · 4 nights". */
  summary?: string;
  [key: string]: unknown;
};

type LineLike = {
  product_category?: string | null;
  ticket_number?: string | null;
  booking_ref?: string | null;
  airline_name?: string | null;
  sector?: string | null;
  service_details?: ServiceDetails | null;
};

export const isAirLine = (t: LineLike) => !t.product_category || t.product_category === "air";

/** Ticket # column: the ticket number, or a non-air line's booking reference. */
export function lineReference(t: LineLike): string | null {
  return t.ticket_number ?? (isAirLine(t) ? null : t.booking_ref ?? null);
}

/** Airline column: the carrier, or the property / train / operator. */
export function lineProvider(t: LineLike): string | null {
  return isAirLine(t) ? t.airline_name ?? null : t.service_details?.title ?? null;
}

/** Sector column: the sector, or the route / city — with the full summary as its tooltip. */
export function lineRoute(t: LineLike): string | null {
  return isAirLine(t) ? t.sector ?? null : t.service_details?.route ?? t.service_details?.summary ?? null;
}
