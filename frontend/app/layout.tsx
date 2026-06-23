import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ShopWave Support — AI Refund Agent",
  description: "AI-powered customer support for ShopWave",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="bg-surface text-white antialiased min-h-screen">
        {children}
      </body>
    </html>
  );
}
