import Image from "next/image";
import Link from "next/link";
import { ArrowRight, FolderOpen } from "lucide-react";

export default function Home() {
  return (
    <main className="shell home">
      <section className="home-center" aria-labelledby="home-title">
        <div className="home-mark-wrap">
          <div className="home-glow" />
          <Image
            className="home-mark"
            src="/brand/matias-mark-light.svg"
            width={500}
            height={500}
            alt=""
            priority  
          />
        </div>
        <h1 id="home-title">Matias <span>3D</span> Studio</h1>
        <nav className="home-actions" aria-label="Começar no Matias 3D Studio">
          <Link className="btn primary" href="/projects/new">
            Criar novo projeto <ArrowRight size={17} />
          </Link>
          <Link className="btn" href="/projects">
            <FolderOpen size={17} /> Ver projetos
          </Link>
        </nav>
      </section>
    </main>
  );
}
