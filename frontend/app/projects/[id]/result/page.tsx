"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { AlertTriangle, ArrowLeftRight, Check, Download, Images, RotateCcw } from "lucide-react";
import { API, Artifact, Job, Project, request, Version } from "@/lib/api";

const Viewer = dynamic(() => import("@/components/Viewer"), { ssr: false });

export default function Result() {
  const { id } = useParams<{ id: string }>();
  const [project, setProject] = useState<Project>();
  const [job, setJob] = useState<Job>();
  const [versions, setVersions] = useState<Version[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [compareId, setCompareId] = useState<string>("");
  const [error, setError] = useState("");

  const load = () => Promise.all([
    request<Project>(`/api/projects/${id}`),
    request<Job>(`/api/projects/${id}/job`).catch(() => undefined),
    request<Version[]>(`/api/projects/${id}/versions`),
    request<Artifact[]>(`/api/projects/${id}/artifacts`),
  ]).then(([projectData, jobData, versionData, artifactData]) => {
    setProject(projectData);
    setJob(jobData);
    setVersions(versionData);
    setArtifacts(artifactData);
    const requested = new URLSearchParams(window.location.search).get("version");
    const validRequested = versionData.some((version) => version.id === requested) ? requested : null;
    setSelectedId((current) => current || validRequested || projectData.primary_version_id || versionData.find((version) => version.status === "completed")?.id || null);
  }).catch((reason) => setError(reason.message));

  useEffect(() => { void load(); }, [id]);

  const selectedVersion = versions.find((version) => version.id === selectedId);
  const compareVersion = versions.find((version) => version.id === compareId);
  const metrics = selectedVersion?.metrics || job?.metrics || {};
  const glb = useMemo(() => [...artifacts]
    .sort((left, right) => right.created_at.localeCompare(left.created_at))
    .find((artifact) => artifact.artifact_type === "glb" && (selectedId ? artifact.version_id === selectedId : artifact.job_id === job?.id)), [artifacts, job?.id, selectedId]);
  const failed = selectedVersion?.status === "failed" || (!selectedVersion && job?.status === "failed");
  const simulated = glb?.artifact_metadata.simulated === true;
  const displayable = Boolean(glb && !simulated && glb.artifact_metadata.displayable !== false);
  const fidelity = Number(metrics.visual_fidelity ?? project?.quality_score ?? 0);
  const confidence = Number(metrics.geometric_confidence ?? 0);
  const beforeOptimization = Number(metrics.triangles_before_optimization ?? 0);
  const finalTriangles = Number(metrics.triangles ?? 0);
  const reduction = beforeOptimization > finalTriangles && beforeOptimization ? Math.round((1 - finalTriangles / beforeOptimization) * 100) : 0;

  async function makePrimary() {
    if (!selectedId) return;
    await request<Version>(`/api/projects/${id}/versions/${selectedId}/primary`, { method: "POST" });
    await load();
  }

  return (
    <main className="shell" style={{ paddingBottom: 60 }}>
      <div className="pagehead">
        <div><h1>O teu modelo 3D</h1><p className="sub">Inspeciona textura, volume e topologia antes de exportar.</p></div>
        <div className="actions" style={{ marginTop: 0 }}>
          <Link className="btn" href={`/projects/${id}/capture`}><Images size={17} /> Adicionar imagens</Link>
          {displayable && glb && <a className="btn primary" href={`${API}/api/projects/${id}/download/${glb.id}`}><Download size={17} /> Descarregar GLB</a>}
        </div>
      </div>

      {error && <p className="error">{error}</p>}
      {!!versions.length && <div className="card row" style={{ marginBottom: 16, flexWrap: "wrap" }}>
        <div><div className="eyebrow">Versão apresentada</div><select className="input" style={{ width: 250, marginTop: 8 }} value={selectedId || ""} onChange={(event) => setSelectedId(event.target.value)}>{versions.map((version) => <option key={version.id} value={version.id}>Versão {version.number} · {version.status}{version.is_primary ? " · principal" : ""}</option>)}</select></div>
        {versions.length > 1 && <div><div className="eyebrow">Comparar métricas</div><select className="input" style={{ width: 250, marginTop: 8 }} value={compareId} onChange={(event) => setCompareId(event.target.value)}><option value="">Escolher outra versão</option>{versions.filter((version) => version.id !== selectedId).map((version) => <option key={version.id} value={version.id}>Versão {version.number} · {version.status}</option>)}</select></div>}
        {selectedVersion?.status === "completed" && !selectedVersion.is_primary && <button className="btn" onClick={() => void makePrimary()}><Check size={16} /> Definir como principal</button>}
      </div>}

      {selectedVersion && compareVersion && <section className="version-compare" aria-label="Comparação de versões">
        {[selectedVersion, compareVersion].map((version) => <article className="card" key={version.id}>
          <div className="row"><strong>Versão {version.number}</strong>{version.is_primary && <span className="badge">Principal</span>}</div>
          <div className="compare-metrics">
            <span>Imagens <strong>{String(version.metrics.input_images ?? version.image_ids?.length ?? "—")}</strong></span>
            <span>Fidelidade estimada <strong>{String(version.metrics.visual_fidelity ?? "—")}%</strong></span>
            <span>Confiança geométrica <strong>{String(version.metrics.geometric_confidence ?? "—")}%</strong></span>
            <span>Triângulos <strong>{String(version.metrics.triangles ?? "—")}</strong></span>
          </div>
          {version.id !== selectedId && <button className="btn" onClick={() => { setCompareId(selectedId || ""); setSelectedId(version.id); }}><ArrowLeftRight size={16} /> Mostrar no viewer</button>}
        </article>)}
      </section>}

      {failed ? <section className="card mock-blocker"><AlertTriangle size={42} color="var(--warning)" /><div><div className="eyebrow" style={{ color: "var(--warning)" }}>Reconstrução incompleta</div><h2>Esta versão não gerou geometria fiável.</h2><p className="sub">{selectedVersion?.warnings?.[0] || job?.error_message}</p><p className="sub">As versões anteriores permanecem intactas. Adiciona vistas das zonas frágeis e cria uma nova versão.</p><Link className="btn primary" href={`/projects/${id}/capture`}><RotateCcw size={17} /> Melhorar referências</Link></div></section>
      : simulated ? <section className="card mock-blocker"><AlertTriangle size={42} color="var(--warning)" /><div><div className="eyebrow" style={{ color: "var(--warning)" }}>Demonstração técnica</div><h2>Este ficheiro é apenas uma geometria de teste.</h2><p className="sub">Não é apresentado como uma reconstrução real. Volta à captura e utiliza um motor disponível.</p><Link className="btn primary" href={`/projects/${id}/capture`}><RotateCcw size={17} /> Reconstruir em modo real</Link></div></section>
      : displayable && glb ? <Viewer url={`${API}/api/projects/${id}/download/${glb.id}?inline=true`} />
      : <div className="card empty">A carregar e verificar o modelo desta versão…</div>}

      {!simulated && !failed && <div className="grid3" style={{ marginTop: 16 }}>
        <div className="card"><div className="eyebrow">Fidelidade visual</div><h2>{fidelity || "—"}%</h2><p className="sub">Semelhança estimada com as referências usadas nesta versão.</p></div>
        <div className="card"><div className="eyebrow">Confiança geométrica</div><h2>{confidence || "—"}%</h2><p className="sub">Cobertura observada e consistência da forma reconstruída.</p></div>
        <div className="card"><div className="eyebrow">Modelo otimizado</div><h2>{String(metrics.triangles ?? "—")} triângulos</h2><p className="sub">{String(metrics.input_images ?? metrics.cameras ?? selectedVersion?.metrics.input_images ?? "—")} imagens · {glb ? (glb.file_size / 1024 / 1024).toFixed(1) : "—"} MB{reduction ? ` · ${reduction}% mais leve` : ""}</p><p className="sub">{String(metrics.texture_mode ?? "Material PBR")}</p></div>
      </div>}
    </main>
  );
}
