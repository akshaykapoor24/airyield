"use client";

// Customer data → Statement → Upload Statement. Its own page — no longer a redirect to
// Internal Statement — so the two sections can evolve separately. See the component.

import CustomerStatementUpload from "@/components/customerStatements/CustomerStatementUpload";

export default function CustomerUploadStatementPage() {
  return <CustomerStatementUpload />;
}
