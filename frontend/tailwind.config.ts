import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        border: "hsl(240 5% 84%)",
        background: "hsl(0 0% 100%)",
        foreground: "hsl(240 10% 4%)",
        muted: "hsl(240 5% 96%)",
        "muted-foreground": "hsl(240 4% 46%)",
        accent: "hsl(243 75% 59%)",
        "accent-foreground": "hsl(0 0% 100%)",
        card: "hsl(0 0% 100%)",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};

export default config;
