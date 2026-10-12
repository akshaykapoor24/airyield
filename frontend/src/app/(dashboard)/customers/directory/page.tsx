import { redirect } from "next/navigation";

// The Customer Directory page was removed from Customer data, which now holds only
// Outgoing deals, Statement and Income Statement. The parties it listed are managed in
// User master (Employee / Agency / Corporate Master). Kept as a redirect so old links and
// bookmarks land somewhere useful instead of a 404.
export default function CustomerDirectoryPage() {
  redirect("/deals?direction=outbound");
}
