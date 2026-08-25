// Central registry for the "User master" section — the parties a user maintains
// (who they work with), as opposed to Billing (which bills those parties).
//
// Imported by BOTH components/layout/Sidebar.tsx (to build the nav children) and
// app/(dashboard)/user-master/layout.tsx (to build the tab strip and the page
// heading), so the two can never drift out of sync.

import { Building, Building2, Contact, type LucideIcon } from "lucide-react";

export type UserMasterTab = {
  slug: string;
  label: string;
  icon: LucideIcon;
  blurb: string;
};

export const USER_MASTER_NAV: UserMasterTab[] = [
  {
    slug: "customer-master",
    label: "Customer Master",
    icon: Contact,
    blurb: "The customers you work with. Add, edit and import them here, then bill them from Customer Billing.",
  },
  {
    slug: "agency-master",
    label: "Agency Master",
    icon: Building2,
    blurb: "Onboard the agencies you float deals to, then their entities and airline login IDs / IATA codes.",
  },
  {
    slug: "corporate-master",
    label: "Corporate Master",
    icon: Building,
    blurb: "The corporates you work with. Add, edit and import them here, then bill them from Corporate Billing.",
  },
  // IATA Commission used to be a fourth tab here. It is one global master, not
  // something each tenant keeps its own copy of, so it now lives in the
  // platform console under Master Governance (/masters/iata-commission).
];

export const userMasterHref = (slug: string) => `/user-master/${slug}`;
