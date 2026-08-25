"use client";

// Which section the statement screens are being viewed in.
//
// The statement list, the ticket list and the statement detail screen are all
// reachable from two paths — the canonical Customer data → Statement section, and
// the older /tickets/* URLs, which still work for deep links and bookmarks. Any
// link OUT of those screens has to stay in whichever one the user is actually in,
// or a Back button silently teleports them to the other section.

import { usePathname } from "next/navigation";

export const CUSTOMER_STATEMENT_BASE = "/customers/statements";
export const INTERNAL_STATEMENT_BASE = "/tickets";

/** The base path for links out of a statement screen. */
export function useStatementSectionBase(): string {
  const pathname = usePathname();
  return pathname?.startsWith(CUSTOMER_STATEMENT_BASE)
    ? CUSTOMER_STATEMENT_BASE
    : INTERNAL_STATEMENT_BASE;
}
