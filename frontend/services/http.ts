import axios, { AxiosError, type InternalAxiosRequestConfig } from "axios";

import { config } from "@/config";
import { workspaceStore } from "@/lib/storage";

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

http.interceptors.request.use((request: InternalAxiosRequestConfig) => {
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
  (response) => response,
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
      refreshPromise = axios
        .post(`${config.apiBaseUrl}/auth/refresh`, undefined, {
          withCredentials: true,
          headers: { "X-CSRF-Token": readCookie("csrf_token") ?? "" },
        })
        .then(() => undefined)
        .catch((refreshError: unknown) => {
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
