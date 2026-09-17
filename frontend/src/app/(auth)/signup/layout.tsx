import type { Metadata } from "next";

// page.tsx is a Client Component and so cannot export metadata; this pass-through layout
// exists only to give the route its tab title ("Create your account — fareqube").
export const metadata: Metadata = { title: "Create your account" };

export default function SignupLayout({ children }: { children: React.ReactNode }) {
  return children;
}
