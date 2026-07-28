import { redirect } from "next/navigation";
import { FIRST_STATEMENT_PATH } from "@/lib/statements";

// The Statements hub lives under /vendors/statements/[category]/[type].
// The bare route redirects to the first type.
export default function StatementsIndex() {
  redirect(FIRST_STATEMENT_PATH);
}
