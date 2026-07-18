import Link from "next/link";
import { Activity, BookOpen, Braces } from "lucide-react";

const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export default function ApiPage() {
  return (
    <main className="shell">
      <div className="pagehead"><div><div className="eyebrow">Integração local</div><h1>API do Matias 3D Studio</h1><p className="sub">Os mesmos projetos, versões e artefactos acessíveis por HTTP.</p></div></div>
      <div className="grid3">
        <article className="card"><BookOpen color="var(--mint)" /><h3>Documentação interativa</h3><p className="sub">Explora os contratos OpenAPI e testa pedidos no teu backend local.</p><a className="btn" href={`${apiUrl}/docs`} target="_blank" rel="noreferrer">Abrir Swagger</a></article>
        <article className="card"><Braces color="var(--mint)" /><h3>Esquema OpenAPI</h3><p className="sub">Usa o esquema JSON para gerar clientes ou automatizar fluxos.</p><a className="btn" href={`${apiUrl}/openapi.json`} target="_blank" rel="noreferrer">Ver esquema</a></article>
        <article className="card"><Activity color="var(--mint)" /><h3>Estado do motor</h3><p className="sub">Confirma a disponibilidade do backend, fila e motores instalados.</p><a className="btn" href={`${apiUrl}/api/health`} target="_blank" rel="noreferrer">Ver estado</a></article>
      </div>
      <p className="sub" style={{ marginTop: 24 }}>Por defeito, a API local está disponível em <code>{apiUrl}</code>. <Link className="text-link" href="/capture-guide">Consulta também o guia de captura.</Link></p>
    </main>
  );
}
