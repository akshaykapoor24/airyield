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
// The sidebar's Internal Statement module: Upload Statement and Create Ticket,
// moved out of the Customer data → Statement header. It only ENTERS tickets —
// what it saves is a customer statement, so links out of it go to
// CUSTOMER_STATEMENT_BASE, where those statements are listed.
export const STATEMENT_ENTRY_BASE = "/internal-statement";

/** The base path for links out of a statement screen. */
export function useStatementSectionBase(): string {
  const pathname = usePathname();
  return pathname?.startsWith(CUSTOMER_STATEMENT_BASE) || pathname?.startsWith(STATEMENT_ENTRY_BASE + "/")
    ? CUSTOMER_STATEMENT_BASE
    : INTERNAL_STATEMENT_BASE;
}
