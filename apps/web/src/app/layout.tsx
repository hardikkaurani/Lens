import type { Metadata } from "next";
import "./globals.css";
import { AppShell } from "@/components/AppShell";

export const metadata: Metadata = {
  title: "LENS — Personal Knowledge Workspace",
  description: "Personal information capture and retrieval system",
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
