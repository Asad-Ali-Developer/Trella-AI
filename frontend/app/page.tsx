"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { tokenStore } from "@/lib/storage";

export default function HomePage() {
  const router = useRouter();

  useEffect(() => {
    if (tokenStore.getAccessToken()) {
      router.replace("/dashboard");
      return;
    }
    router.replace("/login");
  }, [router]);

  return null;
}
