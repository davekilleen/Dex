import type { ReactNode } from "react";
import "./globals.css";

export const metadata = {
  title: "Used Machinery Intelligence Platform",
  description: "Customer matching, valuation, and pricing for used machinery deals.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="site-header">
          <a href="/">Machinery Intelligence</a>
          <nav style={{ display: "flex", gap: 16 }}>
            <a href="/listings">Listings</a>
            <a href="/intake">New Customer Search</a>
          </nav>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
