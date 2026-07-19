"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Box, Plus, Search, Trash2 } from "lucide-react";
import { Project, projectPreviewUrl, projectTypeLabel, request, statusLabel } from "@/lib/api";

export default function Projects() {
  const [items, setItems] = useState<Project[]>([]);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [type, setType] = useState("all");
  const [error, setError] = useState("");
  const load = () => request<Project[]>("/api/projects").then(setItems).catch((reason) => setError(reason.message));

  useEffect(() => { void load(); }, []);

  const filtered = useMemo(() => items.filter((project) => {
    const text = `${project.name} ${project.description} ${project.category}`.toLowerCase();
    return text.includes(query.toLowerCase())
      && (status === "all" || project.status === status)
      && (type === "all" || project.project_type === type);
  }), [items, query, status, type]);

  async function remove(id: string) {
    if (!confirm("Eliminar este projeto, as versões e os respetivos ficheiros?")) return;
    await request(`/api/projects/${id}`, { method: "DELETE" });
    void load();
  }

  return (
    <main className="shell">
      <div className="pagehead">
        <div>
          <h1>Os teus projetos</h1>
          <p className="sub">Compara versões, continua capturas e acompanha cada reconstrução.</p>
        </div>
        <Link className="btn primary" href="/projects/new"><Plus size={17} /> Novo projeto</Link>
      </div>

      <div className="toolbar" aria-label="Filtros de projetos">
        <label style={{ position: "relative" }}>
          <Search size={16} style={{ position: "absolute", left: 12, top: 14, color: "var(--muted)" }} />
          <input className="input" style={{ paddingLeft: 36 }} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Pesquisar projetos" />
        </label>
        <select className="input" style={{ width: 180 }} value={status} onChange={(event) => setStatus(event.target.value)}>
          <option value="all">Todos os estados</option>
          <option value="completed">Concluídos</option>
          <option value="processing">Em processamento</option>
          <option value="failed">Com erro</option>
          <option value="uploading">Em preparação</option>
        </select>
        <select className="input" style={{ width: 180 }} value={type} onChange={(event) => setType(event.target.value)}>
          <option value="all">Todos os tipos</option>
          <option value="ai_multiview">IA Multivista</option>
          <option value="hybrid">Reconstrução híbrida</option>
          <option value="precision_scan">Digitalização precisa</option>
        </select>
      </div>

      {error && <p className="error">{error}</p>}
      {!items.length && !error ? (
        <div className="card empty">
          <Box size={50} />
          <h2>Ainda não tens projetos</h2>
          <p>Cria o primeiro projeto e escolhe o tipo de referências que vais usar.</p>
          <Link className="btn primary" href="/projects/new"><Plus size={17} /> Criar projeto</Link>
        </div>
      ) : !filtered.length ? (
        <div className="card empty"><Search size={42} /><h2>Sem correspondências</h2><p>Altera a pesquisa ou os filtros.</p></div>
      ) : (
        <div className="projects">
          {filtered.map((project) => (
            <article className="card project" key={project.id}>
              <Link className="thumb" href={`/projects/${project.id}`}>
                <img src={projectPreviewUrl(project.id)} alt={`Pré-visualização de ${project.name}`} onError={(event) => { event.currentTarget.style.display = "none"; }} />
              </Link>
              <div className="projectbody">
                <div className="row">
                  <span className={`badge ${project.status === "failed" ? "danger" : ""}`}>{statusLabel[project.status] || project.status}</span>
                  <button className="btn danger" style={{ minHeight: 34, padding: 7 }} onClick={() => remove(project.id)} title="Eliminar"><Trash2 size={15} /></button>
                </div>
                <h3>{project.name}</h3>
                <div className="project-meta">
                  <span>{projectTypeLabel[project.project_type]}</span><span>·</span>
                  <span>{project.image_count} imagens</span><span>·</span>
                  <span>{project.primary_version_number ? `versão ${project.primary_version_number}` : "sem resultado"}</span><span>·</span>
                  <span>{new Intl.DateTimeFormat("pt-PT", { day: "2-digit", month: "short" }).format(new Date(project.updated_at))}</span>
                </div>
                {project.quality_score != null && <div className="project-quality">Qualidade estimada <strong>{project.quality_score}/100</strong></div>}
                {project.current_progress != null && <div className="project-progress" aria-label={`Progresso ${project.current_progress}%`}><span style={{ width: `${project.current_progress}%` }} /></div>}
                <Link className="btn" style={{ width: "100%" }} href={`/projects/${project.id}`}>Abrir projeto</Link>
              </div>
            </article>
          ))}
        </div>
      )}
    </main>
  );
}
