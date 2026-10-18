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

  async me(): Promise<User> {
    const { data } = await http.get<User>("/auth/me");
    return data;
  }

  async logout(): Promise<void> {
    await http.post("/auth/logout");
    workspaceStore.clear();
  }
}

export const authService = new AuthService();
