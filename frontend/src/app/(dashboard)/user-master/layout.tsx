"use client";

// Shell for User master. Owns the page heading for all three sections so each
// page below renders content only. Navigation between the sections is the left
// sidebar — deliberately no in-page tab strip.

import { useSelectedLayoutSegment } from "next/navigation";
import { USER_MASTER_NAV } from "@/lib/userMasterNav";

export default function UserMasterLayout({ children }: { children: React.ReactNode }) {
  // The immediate child segment, e.g. "employee-master".
  const segment = useSelectedLayoutSegment();
  const active = USER_MASTER_NAV.find((t) => t.slug === segment);

  return (
    <div className="space-y-1">
      {/* Title, plus a one-line subtitle where the section sets one. */}
      <div>
        <h1 className="text-lg font-bold text-gray-900 leading-tight">{active?.label ?? "User Master"}</h1>
        {active?.subtitle && <p className="text-xs text-gray-500 mt-0.5">{active.subtitle}</p>}
      </div>

      {children}
    </div>
  );
}
