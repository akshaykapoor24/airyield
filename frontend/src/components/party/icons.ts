import { Building, Contact, type LucideIcon } from "lucide-react";
import type { PartyKind } from "@/lib/party";

// Kept out of lib/party.ts so that module stays plain data (see lib/statements.ts).
export const PARTY_ICON: Record<PartyKind, LucideIcon> = {
  customer: Contact,
  corporate: Building,
};
