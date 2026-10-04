// Vendors data → Payment Module: the consolidator's statement, our own mid-office (MO)
// record of it, and the reconciliation between the two before a payment is made.
// Tabs live in-page with a `?tab=` param — see components/payment/PaymentModuleTabs.tsx.
import PaymentModuleTabs from "@/components/payment/PaymentModuleTabs";

export default function PaymentModulePage() {
  return <PaymentModuleTabs />;
}
