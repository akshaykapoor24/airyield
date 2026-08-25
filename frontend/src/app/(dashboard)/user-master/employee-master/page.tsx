"use client";

// User master → Employee Master. The people you sell tickets to: add, edit,
// import and remove them here. Each one either works for a corporate (picked
// from Corporate Master, which is what Corporate Billing bills through) or is
// an individual / direct customer. Billing one directly happens in Billing →
// Customer Billing (/customers), reachable per-row via the Bill action.

import PartyDirectory from "@/components/party/PartyDirectory";

export default function EmployeeMasterPage() {
  return <PartyDirectory kind="customer" mode="master" />;
}
