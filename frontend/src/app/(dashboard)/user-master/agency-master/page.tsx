import AgencyOnboarding from "@/components/agency/AgencyOnboarding";

// User master → Agency Master. Onboard the agencies you float deals to, plus
// their entities and airline login IDs. Reviewing them (counts + drill-down)
// lives in Customer data → Customer Directory (/customers/directory).
export default function AgencyMasterPage() {
  return <AgencyOnboarding />;
}
