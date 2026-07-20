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
  minimum_images?: number;
  recommended_images?: string;
  real_reconstruction_ready?: boolean;
  pipeline?: {
    key: string;
    label: string;
    description: string;
    uses_generative_ai: boolean;
    uses_photogrammetry: boolean;
    minimum_images?: number;
    recommended_images?: string;
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
    minimum_images: value?.minimum_images,
    recommended_images: value?.recommended_images,
    real_reconstruction_ready: value?.real_reconstruction_ready ?? approved + warnings >= (value?.minimum_images ?? 1),
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

  const isScan = project?.project_type === "reality_scan";
  const modeMinimum = isScan ? 20 : 1;
  const modeCopy = isScan
    ? {
        title: "Digitalização real com 20+ fotografias",
        subtitle: "20+ fotografias reais · mesmo objeto · elevada sobreposição",
        items: ["Duas voltas completas com 70–80% de sobreposição", "Uma volta lateral e outra superior", "Luz suave e exposição constante"],
      }
    : {
        title: "Criação local com uma imagem",
        subtitle: "1 imagem principal · SPAR3D Low VRAM · fallback Stable Fast 3D",
        items: ["Escolhe uma vista a 30–45° que mostre a forma principal", "Usa fundo simples e contraste nítido", "O objeto deve aparecer completo e centrado"],
      };

  const canReconstruct = Boolean(
    report &&
    (report.real_reconstruction_ready ?? report.approved + report.warnings >= modeMinimum) &&
    (isScan ? engine?.photogrammetry?.available : engine?.local_ai?.available || engine?.mode === "mock") &&
    engine?.real_reconstruction,
  );

  return (
    <main className="capture-page shell">
      <div className="pagehead">
        <div>
          <div className="eyebrow">Captura · {project?.name}</div>
          <h1>Adiciona as fotografias</h1>
          <p className="sub">JPG ou PNG · {modeCopy.subtitle}</p>
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
            <p className="sub">ou clica para selecionar {isScan ? "vários ficheiros" : "uma imagem"}</p>
            <input
              hidden
              type="file"
              accept="image/jpeg,image/png"
              multiple={isScan}
              disabled={busy || (!isScan && images.length >= 1)}
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
            <h3>{modeCopy.title}</h3>
            <ul className="checklist">
              {modeCopy.items.map((item) => <li key={item}>{item}</li>)}
              <li>Distância e zoom constantes</li>
              <li>Objeto completo e centrado em todas</li>
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
                  <span>{isScan ? "Consistência entre vistas" : "Qualidade da referência"}</span>
                  <strong>{isScan ? report.structural_consistency_estimate ?? 0 : report.input_quality_score ?? report.score ?? 0}%</strong>
                  <i><b style={{ width: `${isScan ? report.structural_consistency_estimate ?? 0 : report.input_quality_score ?? report.score ?? 0}%` }} /></i>
                </div>
                <div>
                  <span>Cobertura observada estimada</span>
                  <strong>{report.observed_coverage_estimate ?? 0}%</strong>
                  <i><b style={{ width: `${report.observed_coverage_estimate ?? 0}%` }} /></i>
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
              <option value="preview">Rápido · 1 candidato · textura 512 px</option>
              <option value="standard">Equilibrado · 2 candidatos · textura 1024 px</option>
              <option value="high">Alta qualidade · 3 candidatos · textura 2048 px</option>
            </select>
          </label>
          <button className="btn primary" style={{ width: "100%", marginTop: 10 }} disabled={!canReconstruct || busy} onClick={() => void reconstruct()}>
            {isScan ? "Iniciar digitalização real" : "Gerar com IA local"}
          </button>
        </aside>
      </div>
    </main>
  );
}
