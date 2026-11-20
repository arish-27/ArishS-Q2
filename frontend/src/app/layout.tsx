import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Dograh-like AI Voice Agent Platform",
  description: "Enterprise Real-Time AI Voice Agent Development & Deployment Platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased bg-slate-950 text-slate-50 min-h-screen">
        {children}
      </body>
    </html>
  );
}
