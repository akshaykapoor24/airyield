import { redirect } from "next/navigation";

// Create Ticket moved out of Customer data → Statement into the sidebar's
// Internal Statement module. Kept as a redirect so older links still land on it.
export default function CustomerCreateTicketPage() {
  redirect("/internal-statement/create");
}
