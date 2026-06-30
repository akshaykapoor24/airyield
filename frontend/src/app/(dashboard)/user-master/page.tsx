import { redirect } from "next/navigation";

// "User Master" is a sidebar group with two sub-pages (Entity, Login IDs).
// Visiting the group root lands on the first sub-tab.
export default function UserMasterIndex() {
  redirect("/user-master/entity");
}
