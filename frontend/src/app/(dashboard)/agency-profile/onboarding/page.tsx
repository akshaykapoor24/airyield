import { redirect } from "next/navigation";

// Agency onboarding moved into User master → Agency Master. Kept as a redirect
// so older links and the user guides still land somewhere sensible.
export default function AgencyOnboardingPage() {
  redirect("/user-master/agency-master");
}
