"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowRight, Cuboid, Images, Plus, ScanLine } from "lucide-react";
import { Project, projectTypeLabel, request, statusLabel, Version } from "@/lib/api";

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const [project, setProject] = useState<Project>();
  const [versions, setVersions] = useState<Version[]>([]);

  useEffect(() => {
    Promise.all([
      request<Project>(`/api/projects/${id}`),
      request<Version[]>(`/api/projects/${id}/versions`),
    ]).then(([projectData, versionData]) => { setProject(projectData); setVersions(versionData); });
  }, [id]);

  if (!project) return <main className="shell empty">A carregar…</main>;
  const active = project.status === "processing" || project.status === "queued";
  const primaryAction = project.primary_version_id ? `/projects/${id}/result` : active ? `/projects/${id}/processing` : `/projects/${id}/capture`;

  return (
    <main className="shell" style={{ paddingBottom: 60 }}>
      <div className="pagehead">
        <div>
          <span className={`badge ${project.status === "failed" ? "danger" : ""}`}>{statusLabel[project.status]}</span>
          <h1 style={{ marginTop: 15 }}>{project.name}</h1>
          <p className="sub">{project.description || "Sem descrição."} · {projectTypeLabel[project.project_type]}</p>
        </div>
        <div className="actions" style={{ marginTop: 0 }}>
          <Link className="btn" href={`/projects/${id}/capture`}><Plus size={17} /> Adicionar imagens</Link>
          <Link className="btn primary" href={primaryAction}>{project.primary_version_id ? "Ver resultado" : active ? "Acompanhar" : "Continuar"}<ArrowRight size={17} /></Link>
        </div>
      </div>

      <div className="grid3">
        <div className="card"><Images color="var(--mint)" /><h3>{project.image_count} imagens</h3><p className="sub">Originais preservados; podes acrescentar vistas sem eliminar versões anteriores.</p></div>
        <div className="card"><ScanLine color="var(--mint)" /><h3>{project.validation_score ?? "—"}/100</h3><p className="sub">Preparação técnica e cobertura estimada das imagens atuais.</p></div>
        <div className="card"><Cuboid color="var(--mint)" /><h3>{project.quality_score ?? "—"}/100</h3><p className="sub">Qualidade medida da versão principal, quando disponível.</p></div>
      </div>

      <section className="section" style={{ paddingBottom: 0 }}>
        <div className="row"><div><div className="eyebrow">Histórico</div><h2 className="section-title">Versões de reconstrução</h2></div><Link className="btn" href={`/projects/${id}/capture`}><Plus size={16} /> Nova versão</Link></div>
        {!versions.length ? <div className="card empty"><Cuboid size={42} /><h2>Ainda não há versões</h2><p>Valida as imagens e inicia a primeira reconstrução.</p></div> : (
          <div className="grid3">
            {versions.map((version) => (
              <article className="card" key={version.id}>
                <div className="row"><span className="badge">Versão {version.number}</span>{version.is_primary && <span className="badge">Principal</span>}</div>
                <h3>{statusLabel[version.status] || version.status}</h3>
                <p className="sub">{version.engine || "Motor por determinar"} · {new Date(version.created_at).toLocaleString("pt-PT")}</p>
                {version.status === "completed" && <Link className="btn" style={{ width: "100%" }} href={`/projects/${id}/result?version=${version.id}`}>Abrir versão</Link>}
              </article>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
