"use client";

// User master → Customer Master. The customers you work with: add, edit,
// import and remove them here. Billing one happens in Billing → Customer
// Billing (/customers), reachable per-row via the Bill action.

import PartyDirectory from "@/components/party/PartyDirectory";

export default function CustomerMasterPage() {
  return <PartyDirectory kind="customer" mode="master" />;
}
