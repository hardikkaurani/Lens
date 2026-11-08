import type { Metadata } from "next";
import "./globals.css";
import { AppShell } from "@/components/AppShell";
import { AuthProvider } from "@/lib/auth-context";

function getMetadataBase(): URL | undefined {
  const appUrl = process.env.NEXT_PUBLIC_APP_URL;
  if (appUrl) {
    try {
      return new URL(appUrl);
    } catch {
      // In case of invalid URL string, fall back to undefined rather than crashing
      return undefined;
    }
  }
  // In production, do not silently invent a canonical domain; omit metadataBase so relative URLs are retained.
  // In development/test, use localhost for predictable resolution.
  if (process.env.NODE_ENV === "production") {
    return undefined;
  }
  return new URL("http://localhost:3000");
}

export const metadata: Metadata = {
  metadataBase: getMetadataBase(),
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
        <AuthProvider>
          <AppShell>{children}</AppShell>
        </AuthProvider>
      </body>
    </html>
  );
}
