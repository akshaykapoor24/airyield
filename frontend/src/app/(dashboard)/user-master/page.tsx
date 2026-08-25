import { redirect } from "next/navigation";

// "User Master" is a sidebar group with three sub-pages (Customer Master,
// Agency Master, Corporate Master). Visiting the group root lands on the first
// tab. IATA Commission moved to Master Governance — see lib/userMasterNav.ts.
export default function UserMasterIndex() {
  redirect("/user-master/customer-master");
}
