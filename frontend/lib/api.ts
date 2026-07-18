export const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export type ProjectType = "real_photos" | "ai_references" | "hybrid";
export type Project = {
  id: string;
  name: string;
  description: string;
  capture_type: string;
  project_type: ProjectType;
  category: string;
  status: string;
  created_at: string;
  updated_at: string;
  image_count: number;
  validation_score: number | null;
  quality_score: number | null;
  primary_version_id: string | null;
  primary_version_number: number | null;
  current_progress: number | null;
  error_message: string | null;
};
export type ProjectImage = {
  id: string;
  original_filename: string;
  width: number;
  height: number;
  file_size: number;
  validation_status: string;
  validation_messages: string[];
  is_primary: boolean;
  consistency_score: number | null;
};
export type Stage = { name: string; order: number; status: string; progress: number; message: string };
export type Job = {
  id: string;
  version_id: string | null;
  status: string;
  current_stage: string;
  progress: number;
  error_message: string | null;
  metrics: Record<string, unknown>;
  stages: Stage[];
};
export type Version = {
  id: string;
  project_id: string;
  number: number;
  status: string;
  engine: string | null;
  reconstruction_type: ProjectType;
  image_ids: string[];
  primary_image_id: string | null;
  metrics: Record<string, unknown>;
  warnings: string[];
  duration_seconds: number | null;
  is_primary: boolean;
  created_at: string;
  completed_at: string | null;
};
export type Artifact = {
  id: string;
  job_id: string;
  version_id: string | null;
  artifact_type: string;
  filename: string;
  file_size: number;
  artifact_metadata: Record<string, unknown>;
  created_at: string;
};
export type Engine = { mode: string; available: boolean; real_reconstruction: boolean; message: string; pipeline?: string | null };

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...options,
    headers: {
      ...(options?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...options?.headers,
    },
    cache: "no-store",
  });
  if (!response.ok) {
    let message = "Ocorreu um erro inesperado.";
    try {
      const error = await response.json();
      message = error.detail || message;
    } catch {}
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}

export const projectPreviewUrl = (id: string) => `${API}/api/projects/${id}/preview`;
export const statusLabel: Record<string, string> = {
  draft: "Rascunho",
  uploading: "Imagens adicionadas",
  ready: "Pronto",
  queued: "Na fila",
  processing: "A processar",
  completed: "Concluído",
  failed: "Com erro",
  cancelled: "Cancelado",
};
export const projectTypeLabel: Record<string, string> = {
  real_photos: "Fotos reais",
  ai_references: "Referências IA",
  hybrid: "Híbrido",
};
