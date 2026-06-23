import type { Metadata, Viewport } from "next";
import "@fontsource-variable/fraunces";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "ShopWave Returns Desk",
  description: "Refund and returns support for ShopWave orders, decided against the written policy.",
};

export const viewport: Viewport = {
  themeColor: "#0F5E5A",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-paper text-ink font-sans antialiased min-h-screen">
        {children}
      </body>
    </html>
  );
}
