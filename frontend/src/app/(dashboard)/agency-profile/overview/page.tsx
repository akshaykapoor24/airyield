import { redirect } from "next/navigation";

// The agency overview is the Customer Directory. Kept as a redirect so older
// links and the user guides still land somewhere sensible.
export default function AgencyOverviewPage() {
  redirect("/customers/directory");
}
