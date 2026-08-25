"use client";

// Billing → Corporate Billing. A picker: search the corporates you already have
// and click one to bill it. Adding / editing / importing corporates lives in
// User master → Corporate Master (/user-master/corporate-master).

import PartyDirectory from "@/components/party/PartyDirectory";

export default function CorporateBillingPage() {
  return <PartyDirectory kind="corporate" mode="billing" />;
}
