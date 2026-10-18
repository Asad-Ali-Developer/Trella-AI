import axios, { AxiosError, type InternalAxiosRequestConfig } from "axios";

import { config } from "@/config";
import { tokenStore } from "@/lib/storage";
import type { TokenResponse } from "@/lib/types";

const http = axios.create({
  baseURL: config.apiBaseUrl,
  headers: { "Content-Type": "application/json" },
});

let refreshPromise: Promise<string> | null = null;

http.interceptors.request.use((request: InternalAxiosRequestConfig) => {
  const token = tokenStore.getAccessToken();
  if (token) {
    request.headers.Authorization = `Bearer ${token}`;
  }
  const workspaceId = tokenStore.getWorkspaceId();
  if (workspaceId) {
    request.headers["X-Workspace-Id"] = workspaceId;
  }
  return request;
});

http.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as InternalAxiosRequestConfig & {
      _retry?: boolean;
    };
    if (error.response?.status !== 401 || original._retry) {
      return Promise.reject(error);
    }

    const refreshToken = tokenStore.getRefreshToken();
    if (!refreshToken) {
      tokenStore.clear();
      if (typeof window !== "undefined") {
        window.location.href = "/login";
      }
      return Promise.reject(error);
    }

    original._retry = true;

    if (!refreshPromise) {
      refreshPromise = axios
        .post<TokenResponse>(`${config.apiBaseUrl}/auth/refresh`, {
          refresh_token: refreshToken,
        })
        .then(({ data }) => {
          tokenStore.setTokens(data.access_token, data.refresh_token);
          return data.access_token;
        })
        .catch((refreshError: unknown) => {
          tokenStore.clear();
          if (typeof window !== "undefined") {
            window.location.href = "/login";
          }
          throw refreshError;
        })
        .finally(() => {
          refreshPromise = null;
        });
    }

    const newToken = await refreshPromise;
    original.headers.Authorization = `Bearer ${newToken}`;
    return http(original);
  },
);

export default http;
