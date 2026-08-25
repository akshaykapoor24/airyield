// Central registry for the "User master" section — the parties a user maintains
// (who they work with), as opposed to Billing (which bills those parties).
//
// Imported by BOTH components/layout/Sidebar.tsx (to build the nav children) and
// app/(dashboard)/user-master/layout.tsx (to build the tab strip and the page
// heading), so the two can never drift out of sync.

import { Building, Building2, Contact, type LucideIcon } from "lucide-react";

// NOTE ON THE FIRST TAB'S NAME. The table behind it is `customers` and the API
// segment is /customers/ — only the SURFACE is "Employee Master", because what a
// user maintains here is people, each either an employee of a corporate or an
// individual. Billing still calls them customers (Billing → Customer Billing),
// so the two names coexist by design; see lib/party.ts.

export type UserMasterTab = {
  slug: string;
  label: string;
  icon: LucideIcon;
  blurb: string;
};

export const USER_MASTER_NAV: UserMasterTab[] = [
  {
    slug: "employee-master",
    label: "Employee Master",
    icon: Contact,
    blurb: "The people you sell tickets to. Link each one to the corporate they work for, or mark them individual / direct.",
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
