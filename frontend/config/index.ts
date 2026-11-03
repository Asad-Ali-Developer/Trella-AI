export type AppEnvironment = "development" | "staging" | "production";

const env = (process.env.NEXT_PUBLIC_APP_ENV ?? "development") as AppEnvironment;

const apiUrls: Record<AppEnvironment, string> = {
  development: "https://deepclient-backend.onrender.com/api/v1",
  staging: "https://deepclient-backend.onrender.com/api/v1",
  production: "https://deepclient-backend.onrender.com/api/v1",
};

export const config = {
  env,
  apiBaseUrl: process.env.NEXT_PUBLIC_API_URL ?? apiUrls[env] ?? apiUrls.development,
  flags: {
    enableSentry: env !== "development",
  },
} as const;
