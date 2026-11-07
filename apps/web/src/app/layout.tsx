import type { Metadata } from "next";
import "./globals.css";
import { AppShell } from "@/components/AppShell";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_APP_URL || "https://lens.local"),
  title: "LENS — Personal Knowledge Workspace",
  description: "Personal information capture and retrieval system",
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "any" },
      { url: "/branding/favicon-32x32.png", type: "image/png", sizes: "32x32" },
      { url: "/branding/favicon-16x16.png", type: "image/png", sizes: "16x16" },
    ],
    apple: [
      { url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" },
    ],
  },
  openGraph: {
    title: "LENS — Personal Knowledge Workspace",
    description: "Personal information capture and retrieval system",
    images: [
      {
        url: "/branding/lens-logo-preview.png",
        width: 1600,
        height: 960,
        alt: "LENS Official Brand Identity System",
      },
    ],
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="antialiased bg-[#0a0d14] text-slate-100">
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
