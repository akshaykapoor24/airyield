"use client";

// User master → Corporate Master. The corporates you work with: add, edit,
// import and remove them here. Billing one happens in Billing → Corporate
// Billing (/corporates), reachable per-row via the Bill action.

import PartyDirectory from "@/components/party/PartyDirectory";

export default function CorporateMasterPage() {
  return <PartyDirectory kind="corporate" mode="master" />;
}
