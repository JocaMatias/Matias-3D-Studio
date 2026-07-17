"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Box, Plus, Trash2 } from "lucide-react";
import { Project, request, statusLabel } from "@/lib/api";

export default function Projects() {
  const [items, setItems] = useState<Project[]>([]);
  const [error, setError] = useState("");
  const load = () => request<Project[]>("/api/projects").then(setItems).catch((e) => setError(e.message));
  useEffect(() => { void load(); }, []);
  async function remove(id: string) {
    if (!confirm("Eliminar este projeto e os respetivos ficheiros?")) return;
    await request(`/api/projects/${id}`, { method: "DELETE" });
    void load();
  }
  return <main className="shell"><div className="pagehead"><div><div className="eyebrow">Área de trabalho</div><h1>Os teus projetos</h1><p className="sub">Gere capturas, processamento e resultados.</p></div><Link className="btn primary" href="/projects/new"><Plus size={17}/> Novo projeto</Link></div>{error&&<p className="error">{error}</p>}{!items.length&&!error?<div className="card empty"><Box size={50}/><h2>Ainda não tens projetos</h2><p>Cria o primeiro e adiciona fotografias do teu objeto.</p></div>:<div className="projects">{items.map(p=><article className="card project" key={p.id}><div className="thumb"><Box size={64}/></div><div className="projectbody"><div className="row"><span className="badge">{statusLabel[p.status]||p.status}</span><button className="btn danger" style={{padding:7}} onClick={()=>remove(p.id)} title="Eliminar"><Trash2 size={15}/></button></div><h3>{p.name}</h3><p className="sub">{p.image_count} imagens · {new Date(p.updated_at).toLocaleDateString("pt-PT")}</p><Link className="btn" style={{width:"100%"}} href={`/projects/${p.id}`}>Abrir projeto</Link></div></article>)}</div>}</main>;
}
