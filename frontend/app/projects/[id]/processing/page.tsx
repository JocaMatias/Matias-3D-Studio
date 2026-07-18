"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Check, Circle, LoaderCircle, StopCircle } from "lucide-react";
import { Job, request } from "@/lib/api";

export default function Processing() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [job, setJob] = useState<Job>();
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const current = await request<Job>(`/api/projects/${id}/job`);
        if (!active) return;
        setError("");
        setJob(current);
        if (current.status === "completed") router.push(`/projects/${id}/result?version=${current.version_id || ""}`);
        else if (!["failed", "cancelled"].includes(current.status)) timer = setTimeout(poll, 1000);
      } catch (reason) {
        if (!active) return;
        setError((reason as Error).message);
        timer = setTimeout(poll, 2000);
      }
    };
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [id, router]);

  async function cancel() {
    if (!confirm("Cancelar esta reconstrução? As versões anteriores não serão afetadas.")) return;
    const cancelled = await request<Job>(`/api/projects/${id}/job/cancel`, { method: "POST" });
    setJob(cancelled);
  }

  const stopped = job && ["failed", "cancelled"].includes(job.status);
  return (
    <main className="shell" style={{ paddingBottom: 60 }}>
      <div className="pagehead">
        <div><div className="eyebrow">Reconstrução em curso</div><h1>A construir o teu modelo</h1><p className="sub">A fila guarda este trabalho; podes sair da página e regressar mais tarde.</p></div>
        <div style={{ textAlign: "right" }}><div className="score">{job?.progress ?? 0}%</div>{job && !stopped && <button className="btn danger" onClick={() => void cancel()}><StopCircle size={16} /> Cancelar</button>}</div>
      </div>
      {(error || job?.error_message) && <div className="error"><strong>{job?.status === "cancelled" ? "Processamento cancelado." : "O processamento parou."}</strong><p>{error || job?.error_message}</p><Link className="btn" href={`/projects/${id}`}>Voltar ao projeto</Link></div>}
      <div className="progress" style={{ height: 10, marginBottom: 24 }}><i style={{ width: `${job?.progress ?? 0}%` }} /></div>
      <div className="stages">{job?.stages.map((stage) => <div className={`stage ${stage.status === "completed" ? "done" : ""}`} key={stage.name}>{stage.status === "completed" ? <Check color="var(--mint)" /> : stage.status === "processing" ? <LoaderCircle color="var(--mint)" /> : <Circle color="var(--muted)" />}<div><strong>{stage.name}</strong><div className="sub">{stage.message || "Pendente"}</div></div><span>{stage.progress}%</span></div>)}</div>
    </main>
  );
}
