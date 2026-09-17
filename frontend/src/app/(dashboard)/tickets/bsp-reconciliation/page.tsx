// Vendors data → Reconciliation.
//
// The route keeps its original `bsp-reconciliation` segment so existing links and the
// sidebar entry (components/layout/Sidebar.tsx) keep working; the screen behind it now
// covers every source. BSP is the first tab, and still talks to /bsp-reconciliation.
import ReconciliationTabs from "@/components/reconciliation/ReconciliationTabs";

export default function ReconciliationPage() {
  return <ReconciliationTabs />;
}
