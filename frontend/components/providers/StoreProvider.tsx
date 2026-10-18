"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { Provider } from "react-redux";

import { clearSession } from "@/lib/authSlice";
import { makeStore, type AppStore } from "@/lib/store";

export function StoreProvider({ children }: { children: ReactNode }) {
  const storeRef = useRef<AppStore | null>(null);
  if (!storeRef.current) {
    storeRef.current = makeStore();
  }

  useEffect(() => {
    const handleSessionExpired = () => storeRef.current?.dispatch(clearSession());
    window.addEventListener("auth:session-expired", handleSessionExpired);
    return () => window.removeEventListener("auth:session-expired", handleSessionExpired);
  }, []);

  return <Provider store={storeRef.current}>{children}</Provider>;
}