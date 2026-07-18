"use client";

import { ChangeEvent, DragEvent, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Camera, CheckCircle, Cpu, Star, Trash2, Upload } from "lucide-react";
import { API, Engine, Project, ProjectImage, request } from "@/lib/api";

type Report = {
  score: number | null;
  approved: number;
  warnings: number;
  rejected: number;
  messages: string[];
  real_reconstruction_ready?: boolean;
  pipeline?: {
    key: string;
    label: string;
    description: string;
    uses_generative_ai: boolean;
    uses_photogrammetry: boolean;
  };
  visual_fidelity_estimate?: number;
  geometric_confidence_estimate?: number;
  observed_coverage_estimate?: number;
  input_quality_score?: number;
  structural_consistency_estimate?: number;
  view_diversity_estimate?: number;
  next_capture_suggestion?: string;
  photogrammetry_trackability?: {
    level: string;
    score: number;
    label: string;
    reason: string;
  };
};

type ReportResponse = Partial<Report>;

function normalizeReport(
  value: ReportResponse | null | undefined,
  imageData: ProjectImage[],
  fallbackScore: number | null,
): Report {
  const approved = value?.approved ?? imageData.filter((image) => image.validation_status === "approved").length;
  const warnings = value?.warnings ?? imageData.filter((image) => image.validation_status === "warning").length;
  const rejected = value?.rejected ?? imageData.filter((image) => image.validation_status === "rejected").length;
  return {
    score: value?.score ?? fallbackScore,
    approved,
    warnings,
    rejected,
    messages: Array.isArray(value?.messages) ? value.messages : [],
    real_reconstruction_ready: value?.real_reconstruction_ready ?? approved + warnings >= 5,
    pipeline: value?.pipeline,
    visual_fidelity_estimate: value?.visual_fidelity_estimate,
    geometric_confidence_estimate: value?.geometric_confidence_estimate,
    observed_coverage_estimate: value?.observed_coverage_estimate,
    input_quality_score: value?.input_quality_score,
    structural_consistency_estimate: value?.structural_consistency_estimate,
    view_diversity_estimate: value?.view_diversity_estimate,
    next_capture_suggestion: value?.next_capture_suggestion,
    photogrammetry_trackability: value?.photogrammetry_trackability,
  };
}

export default function Capture() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [project, setProject] = useState<Project>();
  const [images, setImages] = useState<ProjectImage[]>([]);
  const [engine, setEngine] = useState<Engine>();
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState(false);
  const [qualityProfile, setQualityProfile] = useState("standard");
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");

  const load = () => Promise.all([
    request<Project>(`/api/projects/${id}`),
    request<ProjectImage[]>(`/api/projects/${id}/images`),
    request<Engine>("/api/reconstruction/engine"),
    request<ReportResponse>(`/api/projects/${id}/validation`),
  ]).then(([projectData, imageData, engineData, reportData]) => {
    setProject(projectData);
    setImages(imageData);
    setEngine(engineData);
    setReport(
      projectData.validation_score === null
        ? null
        : normalizeReport(reportData, imageData, projectData.validation_score),
    );
  });

  useEffect(() => { void load(); }, [id]);

  async function upload(files: FileList | File[]) {
    if (!files.length) return;
    setBusy(true);
    setError("");
    const body = new FormData();
    Array.from(files).forEach((file) => body.append("files", file));
    try {
      await request(`/api/projects/${id}/images`, { method: "POST", body });
      await load();
      setReport(null);
    } catch (uploadError) {
      setError((uploadError as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(imageId: string) {
    await request(`/api/projects/${id}/images/${imageId}`, { method: "DELETE" });
    await load();
    setReport(null);
  }

  async function setPrimary(imageId: string) {
    await request(`/api/projects/${id}/images/${imageId}/primary`, { method: "POST" });
    await load();
  }

  async function validate() {
    setBusy(true);
    setError("");
    try {
      const validated = await request<ReportResponse>(`/api/projects/${id}/validate`, { method: "POST" });
      setReport(normalizeReport(validated, images, project?.validation_score ?? null));
      await load();
    } catch (validationError) {
      setError((validationError as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function reconstruct() {
    setBusy(true);
    setError("");
    try {
      await request(`/api/projects/${id}/reconstruct?quality_profile=${qualityProfile}`, { method: "POST" });
      router.push(`/projects/${id}/processing`);
    } catch (reconstructionError) {
      setError((reconstructionError as Error).message);
      setBusy(false);
    }
  }

  function drop(event: DragEvent) {
    event.preventDefault();
    setDrag(false);
    void upload(event.dataTransfer.files);
  }

  const canReconstruct = Boolean(
    report &&
    (report.real_reconstruction_ready ?? report.approved + report.warnings >= 5) &&
    engine?.available &&
    engine.real_reconstruction,
  );

  return (
    <main className="capture-page shell">
      <div className="pagehead">
        <div>
          <div className="eyebrow">Captura · {project?.name}</div>
          <h1>Adiciona as fotografias</h1>
          <p className="sub">JPG ou PNG · 5–10 imagens para começar · mais vistas úteis aumentam a precisão</p>
        </div>
        <span className="badge">{images.length} imagens carregadas</span>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="layout">
        <section>
          <label
            className={`drop ${drag ? "active" : ""}`}
            onDragOver={(event) => { event.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={drop}
          >
            <Upload size={36} color="var(--mint)" />
            <h3>{busy ? "A processar…" : "Arrasta fotografias para aqui"}</h3>
            <p className="sub">ou clica para selecionar vários ficheiros</p>
            <input
              hidden
              type="file"
              accept="image/jpeg,image/png"
              multiple
              disabled={busy}
              onChange={(event: ChangeEvent<HTMLInputElement>) => event.target.files && void upload(event.target.files)}
            />
          </label>
          <div className="gallery">
            {images.map((image) => (
              <div className="image" key={image.id} title={(image.validation_messages ?? []).join("\n")}>
                <img src={`${API}/api/projects/${id}/images/${image.id}/thumbnail`} alt={image.original_filename} />
                <button type="button" onClick={() => void remove(image.id)} title="Remover"><Trash2 size={15} /></button>
                <button type="button" style={{ left: 7, right: "auto", color: image.is_primary ? "var(--mint)" : "white" }} onClick={() => void setPrimary(image.id)} title="Definir como referência principal"><Star size={15} fill={image.is_primary ? "currentColor" : "none"} /></button>
                <span className="flag">{image.is_primary ? "principal" : image.validation_status !== "pending" ? image.validation_status : "por validar"}</span>
              </div>
            ))}
          </div>
        </section>

        <aside>
          <div className="card">
            <Camera color="var(--mint)" />
            <h3>{project?.project_type === "ai_references" ? "Referências IA consistentes" : project?.project_type === "hybrid" ? "Captura híbrida coerente" : "Para um bom modelo com 5–10 fotos"}</h3>
            <ul className="checklist">
              <li>{project?.project_type === "ai_references" ? "Marca com a estrela a vista que define o objeto" : "Frente, traseira, esquerda e direita"}</li>
              <li>Uma vista ligeiramente superior</li>
              <li>{project?.project_type === "ai_references" ? "Mantém proporções, materiais e detalhes idênticos" : "Luz suave; desliga o flash"}</li>
              <li>Distância e zoom constantes</li>
              <li>Objeto completo e centrado em todas</li>
              <li>Fotos adicionais refinam zonas ocultas</li>
            </ul>
          </div>

          <div className="card" style={{ marginTop: 14 }}>
            <Cpu color={engine?.available ? "var(--mint)" : "var(--warning)"} />
            <h3>Motor de reconstrução</h3>
            <p className="sub">{engine?.message ?? "A verificar…"}</p>
            {engine?.pipeline && <span className="badge">{engine.pipeline}</span>}
          </div>

          {report && (
            <div className="card" style={{ marginTop: 14 }}>
              <div className="score">{report.score ?? 0}/100</div>
              <p>Preparação da captura</p>
              <p className="sub">{report.approved} aprovadas · {report.warnings} avisos · {report.rejected} rejeitadas</p>
              {report.pipeline && (
                <div className="strategy">
                  <span className="badge">{report.pipeline.label}</span>
                  <p className="sub">{report.pipeline.description}</p>
                </div>
              )}
              {report.photogrammetry_trackability && (
                <div className="strategy">
                  <span className="badge">Textura rastreável: {report.photogrammetry_trackability.label}</span>
                  <p className="sub">{report.photogrammetry_trackability.reason}</p>
                </div>
              )}
              <div className="metrics">
                <div>
                  <span>Qualidade das imagens</span>
                  <strong>{report.input_quality_score ?? report.score ?? 0}%</strong>
                  <i><b style={{ width: `${report.input_quality_score ?? report.score ?? 0}%` }} /></i>
                </div>
                <div>
                  <span>Consistência entre vistas</span>
                  <strong>{report.structural_consistency_estimate ?? 0}%</strong>
                  <i><b style={{ width: `${report.structural_consistency_estimate ?? 0}%` }} /></i>
                </div>
                <div>
                  <span>Diversidade de ângulos</span>
                  <strong>{report.view_diversity_estimate ?? 0}%</strong>
                  <i><b style={{ width: `${report.view_diversity_estimate ?? 0}%` }} /></i>
                </div>
                <div>
                  <span>Fidelidade visual</span>
                  <strong>{report.visual_fidelity_estimate ?? 0}%</strong>
                  <i><b style={{ width: `${report.visual_fidelity_estimate ?? 0}%` }} /></i>
                </div>
                <div>
                  <span>Confiança geométrica</span>
                  <strong>{report.geometric_confidence_estimate ?? 0}%</strong>
                  <i><b style={{ width: `${report.geometric_confidence_estimate ?? 0}%` }} /></i>
                </div>
              </div>
              {report.next_capture_suggestion && (
                <p className="suggestion"><strong>Próxima foto:</strong> {report.next_capture_suggestion}</p>
              )}
              {report.messages.map((message) => <p className="error" key={message}>{message}</p>)}
            </div>
          )}

          <button className="btn" style={{ width: "100%", marginTop: 14 }} disabled={!images.length || busy} onClick={() => void validate()}>
            <CheckCircle size={17} /> Validar imagens
          </button>
          <label className="field" style={{ marginTop: 12 }}>
            <span>Perfil da malha</span>
            <select className="input" value={qualityProfile} onChange={(event) => setQualityProfile(event.target.value)}>
              <option value="preview">Pré-visualização · ~25 mil faces</option>
              <option value="standard">Equilibrado · ~60 mil faces</option>
              <option value="high">Alta qualidade · ~120 mil faces</option>
            </select>
          </label>
          <button className="btn primary" style={{ width: "100%", marginTop: 10 }} disabled={!canReconstruct || busy} onClick={() => void reconstruct()}>
            {report?.pipeline?.key === "hybrid" ? "Reconstruir em modo híbrido" : "Gerar modelo com IA"}
          </button>
        </aside>
      </div>
    </main>
  );
}
