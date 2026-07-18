import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import "./globals.css";
import "./mock.css";

export const metadata: Metadata = {
  title: { default: "Matias 3D Studio", template: "%s · Matias 3D Studio" },
  description: "Reconstrução 3D local a partir de fotografias e referências visuais.",
  icons: {
    icon: [{ url: "/brand/matias-mark-light.svg", type: "image/svg+xml" }],
    shortcut: "/brand/matias-mark-light.svg",
    apple: "/favicon.png",
  },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt">
      <body>
        <header className="shell nav">
          <Link href="/" className="brand" aria-label="Matias 3D Studio — início">
            <Image src="/brand/matias-mark-light.svg" width={34} height={34} alt="" priority />
            <span>Matias <strong>3D</strong> Studio</span>
          </Link>
          <nav className="navlinks" aria-label="Navegação principal">
            <Link href="/projects">Projetos</Link>
            <Link href="/capture-guide">Guia de captura</Link>
            <Link href="/api">API</Link>
          </nav>
        </header>
        {children}
      </body>
    </html>
  );
}
