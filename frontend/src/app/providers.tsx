"use client";

import { Provider } from "react-redux";
import { QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "react-hot-toast";
import { store } from "@/store";
import { queryClient } from "@/lib/queryClient";

/**
 * Every client-side provider the app needs, in one client component.
 *
 * These live here rather than in the root layout so that the layout can stay a Server
 * Component: `export const metadata` is only honoured in Server Components, and with the
 * layout marked "use client" no route could set a browser tab title — every page outside
 * the home page showed its raw URL in the tab instead.
 */
export default function Providers({ children }: { children: React.ReactNode }) {
  return (
    <Provider store={store}>
      <QueryClientProvider client={queryClient}>
        {children}
        <Toaster position="top-right" />
      </QueryClientProvider>
    </Provider>
  );
}
