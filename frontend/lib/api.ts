export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type Project = { id:string; name:string; description:string; capture_type:string; status:string; created_at:string; updated_at:string; image_count:number; validation_score:number|null; quality_score:number|null; error_message:string|null };
export type ProjectImage = { id:string; original_filename:string; width:number; height:number; file_size:number; validation_status:string; validation_messages:string[] };
export type Stage = { name:string; order:number; status:string; progress:number; message:string };
export type Job = { id:string; status:string; current_stage:string; progress:number; error_message:string|null; metrics:Record<string,unknown>; stages:Stage[] };
export type Artifact = { id:string; job_id:string; artifact_type:string; filename:string; file_size:number; artifact_metadata:Record<string,unknown>; created_at:string };
export type Engine = { mode:string; available:boolean; real_reconstruction:boolean; message:string; pipeline?:string|null };

export async function request<T>(path:string, options?:RequestInit):Promise<T>{
  const response=await fetch(`${API}${path}`, {...options, headers:{...(options?.body instanceof FormData?{}:{"Content-Type":"application/json"}),...options?.headers}, cache:"no-store"});
  if(!response.ok){ let message="Ocorreu um erro inesperado."; try{const e=await response.json(); message=e.detail||message}catch{} throw new Error(message) }
  if(response.status===204) return undefined as T;
  return response.json();
}
export const statusLabel:Record<string,string>={draft:"Rascunho",uploading:"A carregar",ready:"Pronto",queued:"Na fila",processing:"A processar",completed:"Concluído",failed:"Com erro"};
