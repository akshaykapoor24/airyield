"use client";

// Billing → Customer Billing. A picker: search the customers you already have
// and click one to bill it. Adding / editing / importing customers lives in
// User master → Customer Master (/user-master/customer-master).

import PartyDirectory from "@/components/party/PartyDirectory";

export default function CustomerBillingPage() {
  return <PartyDirectory kind="customer" mode="billing" />;
}
