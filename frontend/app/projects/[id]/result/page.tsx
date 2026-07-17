"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { AlertTriangle, Download, RotateCcw } from "lucide-react";
import { API, Artifact, Job, Project, request } from "@/lib/api";

const Viewer = dynamic(() => import("@/components/Viewer"), { ssr: false });

export default function Result() {
  const { id } = useParams<{ id: string }>();
  const [project, setProject] = useState<Project>();
  const [job, setJob] = useState<Job>();
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);

  useEffect(() => {
    Promise.all([
      request<Project>(`/api/projects/${id}`),
      request<Job>(`/api/projects/${id}/job`),
      request<Artifact[]>(`/api/projects/${id}/artifacts`),
    ]).then(([projectData, jobData, artifactData]) => {
      setProject(projectData);
      setJob(jobData);
      setArtifacts(artifactData);
    });
  }, [id]);

  const glb = [...artifacts]
    .sort((left, right) => right.created_at.localeCompare(left.created_at))
    .find((artifact) => artifact.artifact_type === "glb" && artifact.job_id === job?.id);
  const failed = job?.status === "failed";
  const simulated = glb?.artifact_metadata.simulated === true;
  const generative = glb?.artifact_metadata.generative_ai === true;
  const displayable = Boolean(glb && !simulated && glb.artifact_metadata.displayable !== false);
  const fidelity = Number(job?.metrics.visual_fidelity ?? project?.quality_score ?? 0);
  const confidence = Number(job?.metrics.geometric_confidence ?? 0);
  const candidates = Number(job?.metrics.candidates_generated ?? 0);
  const beforeOptimization = Number(job?.metrics.triangles_before_optimization ?? 0);
  const finalTriangles = Number(job?.metrics.triangles ?? 0);
  const reduction = beforeOptimization > finalTriangles && beforeOptimization
    ? Math.round((1 - finalTriangles / beforeOptimization) * 100)
    : 0;

  return (
    <main className="shell">
      <div className="pagehead">
        <div>
          <div className="eyebrow">Resultado · {project?.name}</div>
          <h1>O teu modelo 3D</h1>
          <p className="sub">Arrasta para rodar, usa a roda para zoom e o botão direito para mover.</p>
        </div>
        {displayable && glb && (
          <a className="btn primary" href={`${API}/api/projects/${id}/download/${glb.id}`}>
            <Download size={17} /> Descarregar GLB
          </a>
        )}
      </div>

      {failed ? (
        <section className="card mock-blocker">
          <AlertTriangle size={42} color="var(--warning)" />
          <div>
            <div className="eyebrow" style={{ color: "var(--warning)" }}>Captura insuficiente</div>
            <h2>Não foi gerado um modelo porque a geometria não era fiável.</h2>
            <p className="sub">{job.error_message}</p>
            <p className="sub">
              Nenhum GLB degradado foi publicado. Adiciona fotos intermédias sem flash e volta a validar a captura.
            </p>
            <Link className="btn primary" href={`/projects/${id}/capture`}>
              <RotateCcw size={17} /> Melhorar a captura
            </Link>
          </div>
        </section>
      ) : simulated ? (
        <section className="card mock-blocker">
          <AlertTriangle size={42} color="var(--warning)" />
          <div>
            <div className="eyebrow" style={{ color: "var(--warning)" }}>Resultado mock removido</div>
            <h2>Isto não é uma reconstrução da tua chávena.</h2>
            <p className="sub">
              O ficheiro anterior continha apenas um triângulo de teste. Já não o mostramos como modelo.
              Volta à captura e inicia uma reconstrução multivista assistida por IA.
            </p>
            <Link className="btn primary" href={`/projects/${id}/capture`}>
              <RotateCcw size={17} /> Reconstruir em modo real
            </Link>
          </div>
        </section>
      ) : displayable && glb ? (
        <>
          {generative && (
            <div className="card" style={{ marginBottom: 16 }}>
              <div className="eyebrow">Geometria assistida por IA</div>
              <p className="sub" style={{ marginBottom: 0 }}>
                {candidates > 1 ? `${candidates} candidatos comparados · ` : ""}
                melhor forma selecionada automaticamente · material PBR limpo, sem colar a fotografia na malha.
              </p>
            </div>
          )}
          <Viewer url={`${API}/api/projects/${id}/download/${glb.id}?inline=true`} />
        </>
      ) : (
        <div className="card empty">A carregar e verificar o modelo…</div>
      )}

      {!simulated && !failed && (
        <div className="grid3">
          <div className="card"><div className="eyebrow">Fidelidade visual</div><h2>{fidelity || "—"}%</h2><p className="sub">Semelhança estimada com as fotografias enviadas.</p></div>
          <div className="card"><div className="eyebrow">Confiança geométrica</div><h2>{confidence || "—"}%</h2><p className="sub">Quanto da forma está apoiado por vistas reais.</p></div>
          <div className="card"><div className="eyebrow">Modelo otimizado</div><h2>{String(job?.metrics.triangles ?? "—")} triângulos</h2><p className="sub">{String(job?.metrics.input_images ?? job?.metrics.cameras ?? "—")} imagens · {glb ? (glb.file_size / 1024 / 1024).toFixed(1) : "—"} MB{reduction ? ` · ${reduction}% mais leve` : ""}</p><p className="sub">{String(job?.metrics.texture_mode ?? "Material PBR")}</p></div>
        </div>
      )}
    </main>
  );
}
