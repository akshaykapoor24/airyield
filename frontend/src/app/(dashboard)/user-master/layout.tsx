"use client";

// Shell for User master. Owns the page heading for all three sections so each
// page below renders content only. Navigation between the sections is the left
// sidebar — deliberately no in-page tab strip.

import { useSelectedLayoutSegment } from "next/navigation";
import { USER_MASTER_NAV } from "@/lib/userMasterNav";

export default function UserMasterLayout({ children }: { children: React.ReactNode }) {
  // The immediate child segment, e.g. "customer-master".
  const segment = useSelectedLayoutSegment();
  const active = USER_MASTER_NAV.find((t) => t.slug === segment);

  return (
    <div className="space-y-4">
      <div>
        <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">User Master</p>
        <h1 className="text-xl font-bold text-gray-900">{active?.label ?? "User Master"}</h1>
        <p className="text-xs text-gray-500 mt-0.5">
          {active?.blurb ?? "The customers, agencies and corporates you work with."}
        </p>
      </div>

      {children}
    </div>
  );
}
