import { tokenStore } from "@/lib/storage";
import type { AuthResponse, TokenResponse, User } from "@/lib/types";
import http from "@/services/http";

class AuthService {
  async signup(payload: {
    email: string;
    password: string;
    name: string;
  }): Promise<AuthResponse> {
    const { data } = await http.post<AuthResponse>("/auth/signup", payload);
    tokenStore.setTokens(data.tokens.access_token, data.tokens.refresh_token);
    return data;
  }

  async login(payload: {
    email: string;
    password: string;
  }): Promise<AuthResponse> {
    const { data } = await http.post<AuthResponse>("/auth/login", payload);
    tokenStore.setTokens(data.tokens.access_token, data.tokens.refresh_token);
    return data;
  }

  async me(): Promise<User> {
    const { data } = await http.get<User>("/auth/me");
    return data;
  }

  async refresh(refreshToken: string): Promise<TokenResponse> {
    const { data } = await http.post<TokenResponse>("/auth/refresh", {
      refresh_token: refreshToken,
    });
    tokenStore.setTokens(data.access_token, data.refresh_token);
    return data;
  }

  logout(): void {
    tokenStore.clear();
  }
}

export const authService = new AuthService();
