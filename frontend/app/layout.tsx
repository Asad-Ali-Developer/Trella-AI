import type { Metadata } from "next";
import { Inter } from "next/font/google";

import { StoreProvider } from "@/components/providers/StoreProvider";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Client Insights",
  description: "Trello + AI client insights",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <StoreProvider>{children}</StoreProvider>
      </body>
    </html>
  );
}
