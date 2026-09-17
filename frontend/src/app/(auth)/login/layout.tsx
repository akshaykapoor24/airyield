import type { Metadata } from "next";

// page.tsx is a Client Component and so cannot export metadata; this pass-through layout
// exists only to give the route its tab title ("Sign in — fareqube").
export const metadata: Metadata = { title: "Sign in" };

export default function LoginLayout({ children }: { children: React.ReactNode }) {
  return children;
}
