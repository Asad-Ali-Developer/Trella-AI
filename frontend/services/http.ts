import axios, { AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from "axios";

import { config } from "@/config";
import { workspaceStore } from "@/lib/storage";

const ACCESS_TOKEN_KEY = "ci.access_token";
const REFRESH_TOKEN_KEY = "ci.refresh_token";

const http = axios.create({
  baseURL: config.apiBaseUrl,
  headers: { "Content-Type": "application/json" },
  withCredentials: true,
});

let refreshPromise: Promise<void> | null = null;

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const cookie = document.cookie
    .split("; ")
    .find((item) => item.startsWith(`${name}=`));
  return cookie ? decodeURIComponent(cookie.slice(name.length + 1)) : null;
}

function saveAuthHeaders(response: AxiosResponse): void {
  if (typeof window === "undefined") return;
  const accessToken = response.headers["x-access-token"];
  const refreshToken = response.headers["x-refresh-token"];
  if (typeof accessToken === "string" && accessToken) {
    localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
  }
  if (typeof refreshToken === "string" && refreshToken) {
    localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
  }
}

export function clearStoredTokens(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
}

http.interceptors.request.use((request: InternalAxiosRequestConfig) => {
  if (typeof window !== "undefined") {
    const accessToken = localStorage.getItem(ACCESS_TOKEN_KEY);
    if (accessToken && !request.headers.Authorization) {
      request.headers.Authorization = `Bearer ${accessToken}`;
    }
  }
  const method = request.method?.toUpperCase();
  if (method && !["GET", "HEAD", "OPTIONS"].includes(method)) {
    const csrfToken = readCookie("csrf_token");
    if (csrfToken) request.headers["X-CSRF-Token"] = csrfToken;
  }
  const workspaceId = workspaceStore.getWorkspaceId();
  if (workspaceId && !request.headers["X-Workspace-Id"]) {
    request.headers["X-Workspace-Id"] = workspaceId;
  }
  return request;
});

http.interceptors.response.use(
  (response) => {
    saveAuthHeaders(response);
    if (response.config.url?.endsWith("/auth/logout")) {
      clearStoredTokens();
    }
    return response;
  },
  async (error: AxiosError) => {
    const original = error.config as InternalAxiosRequestConfig & {
      _retry?: boolean;
    };
    const url = original?.url ?? "";
    const isAuthEndpoint = [
      "/auth/login",
      "/auth/signup",
      "/auth/refresh",
      "/auth/logout",
    ].some((path) => url.endsWith(path));
    if (
      error.response?.status !== 401 ||
      !original ||
      original._retry ||
      isAuthEndpoint
    ) {
      return Promise.reject(error);
    }

    original._retry = true;

    if (!refreshPromise) {
      const storedRefresh =
        typeof window !== "undefined" ? localStorage.getItem(REFRESH_TOKEN_KEY) : null;
      refreshPromise = axios
        .post(
          `${config.apiBaseUrl}/auth/refresh`,
          storedRefresh ? { refresh_token: storedRefresh } : undefined,
          {
            withCredentials: true,
            headers: { "X-CSRF-Token": readCookie("csrf_token") ?? "" },
          },
        )
        .then((res) => {
          saveAuthHeaders(res);
        })
        .catch((refreshError: unknown) => {
          clearStoredTokens();
          if (typeof window !== "undefined") {
            window.dispatchEvent(new Event("auth:session-expired"));
          }
          workspaceStore.clear();
          if (typeof window !== "undefined") {
            window.location.assign("/login");
          }
          throw refreshError;
        })
        .finally(() => {
          refreshPromise = null;
        });
    }

    await refreshPromise;
    return http(original);
  },
);

export default http;
