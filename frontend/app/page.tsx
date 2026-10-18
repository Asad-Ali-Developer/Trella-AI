"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { clearSession, setAuthenticatedUser } from "@/lib/authSlice";
import { useAppDispatch } from "@/lib/hooks";
import { authService } from "@/services/AuthService";

export default function HomePage() {
  const router = useRouter();
  const dispatch = useAppDispatch();

  useEffect(() => {
    void authService
      .me()
      .then((user) => {
        dispatch(setAuthenticatedUser(user));
        router.replace("/dashboard");
      })
      .catch(() => {
        dispatch(clearSession());
        router.replace("/login");
      });
  }, [dispatch, router]);

  return null;
}
