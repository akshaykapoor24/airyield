"use client";

// The notice a team member sees on the parts of My Profile only the Super Admin can change
// — company details, entities, login IDs. Says who manages it and what they can still do,
// so a missing Add button reads as a rule rather than a bug.

import { Lock } from "lucide-react";

export default function ManagedByAdminNote({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2.5 rounded-xl border border-sky-200 bg-sky-50/70 px-3.5 py-2.5">
      <span className="w-6 h-6 rounded-lg bg-white border border-sky-200 text-sky-600 flex items-center justify-center shrink-0">
        <Lock className="w-3.5 h-3.5" />
      </span>
      <p className="text-[11px] text-sky-900 leading-relaxed pt-0.5">{children}</p>
    </div>
  );
}
