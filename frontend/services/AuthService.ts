import { workspaceStore } from "@/lib/storage";
import type { AuthResponse, User } from "@/lib/types";
import http from "@/services/http";

class AuthService {
  async signup(payload: {
    email: string;
    password: string;
    name: string;
  }): Promise<AuthResponse> {
    const { data } = await http.post<AuthResponse>("/auth/signup", payload);
    return data;
  }

  async login(payload: {
    email: string;
    password: string;
  }): Promise<AuthResponse> {
    const { data } = await http.post<AuthResponse>("/auth/login", payload);
    return data;
  }

  async googleAuth(payload?: {
    email?: string;
    name?: string;
    credential?: string;
    code?: string;
  }): Promise<AuthResponse> {
    const { data } = await http.post<AuthResponse>("/auth/google", payload ?? {});
    return data;
  }

  async requestPasswordReset(email: string): Promise<void> {
    await http.post("/auth/password-reset/request", { email });
  }

  async resetPassword(token: string, password: string): Promise<void> {
    await http.post("/auth/password-reset/confirm", { token, password });
  }

  async me(): Promise<User> {
    const { data } = await http.get<User>("/auth/me");
    return data;
  }

  async updateProfile(payload: { name: string }): Promise<User> {
    const { data } = await http.patch<User>("/auth/me", payload);
    return data;
  }

  async changePassword(payload: {
    current_password: string;
    new_password: string;
  }): Promise<void> {
    await http.post("/auth/change-password", payload);
  }

  async logout(): Promise<void> {
    await http.post("/auth/logout");
    workspaceStore.clear();
  }
}

export const authService = new AuthService();
