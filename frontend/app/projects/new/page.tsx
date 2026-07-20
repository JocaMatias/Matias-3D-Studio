"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Lock, ScanLine, Sparkles } from "lucide-react";
import { Project, ProjectType, request } from "@/lib/api";

const profiles = [
  ["auto", "Automático"],
  ["compact", "Objeto compacto"],
  ["thin_parts", "Partes finas"],
  ["multi_component", "Várias peças"],
  ["handled_container", "Recipiente com pega"],
  ["mechanical", "Mecânico"],
  ["organic", "Orgânico"],
  ["architecture", "Arquitetura"],
] as const;

export default function NewProject() {
  const router = useRouter();
  const [projectType, setProjectType] = useState<ProjectType>("ai_generation");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      const project = await request<Project>("/api/projects", {
        method: "POST",
        body: JSON.stringify({ ...Object.fromEntries(form), project_type: projectType }),
      });
      router.push(`/projects/${project.id}/capture`);
    } catch (reason) {
      setError((reason as Error).message);
      setBusy(false);
    }
  }

  return (
    <main className="shell">
      <form className="card form" onSubmit={submit}>
        <h1>Como queres criar o modelo?</h1>
        <p className="sub">A versão atual cria localmente a partir de uma imagem. A digitalização real será adicionada numa fase própria.</p>
        {error && <p className="error">{error}</p>}

        <div className="field">
          <label>Modo</label>
          <div className="choice-grid">
            <button className={`choice ${projectType === "ai_generation" ? "active" : ""}`} type="button" onClick={() => setProjectType("ai_generation")}>
              <Sparkles size={22} color="var(--mint)" />
              <strong style={{ display: "block", margin: "10px 0 5px", color: "var(--text)" }}>Criar com IA</strong>
              <span className="sub" style={{ fontSize: 12 }}>Uma imagem principal. O motor local estima as zonas invisíveis, cria textura e exporta GLB.</span>
            </button>
            <button className="choice" type="button" disabled title="Em desenvolvimento">
              <ScanLine size={22} color="var(--muted)" />
              <strong style={{ display: "block", margin: "10px 0 5px", color: "var(--text)" }}>Digitalizar objeto real</strong>
              <span className="sub" style={{ fontSize: 12 }}>Muitas fotografias reais, geometria baseada em observação e textura fotográfica.</span>
              <span className="badge" style={{ marginTop: 10 }}><Lock size={12} /> Em desenvolvimento</span>
            </button>
          </div>
        </div>

        <div className="field">
          <label>Nome do projeto</label>
          <input className="input" name="name" required minLength={2} placeholder="Ex.: Avião antigo" />
        </div>
        <div className="field">
          <label>Descrição opcional</label>
          <textarea className="input" name="description" rows={3} placeholder="Material, detalhes importantes ou objetivo do modelo" />
        </div>
        <div className="field">
          <label>Perfil do objeto</label>
          <select className="input" name="object_profile" defaultValue="auto">
            {profiles.map(([value, label]) => <option value={value} key={value}>{label}</option>)}
          </select>
          <span className="sub">Ajuda a preservar peças pequenas, cavidades, superfícies planas e partes finas durante a avaliação.</span>
        </div>
        <div className="field">
          <label>Categoria</label>
          <select className="input" name="category" defaultValue="generic">
            <option value="generic">Objeto genérico</option>
            <option value="product">Produto</option>
            <option value="character">Personagem</option>
            <option value="vehicle">Veículo</option>
            <option value="architecture">Arquitetura</option>
            <option value="furniture">Mobiliário</option>
            <option value="other">Outro</option>
          </select>
        </div>
        <input type="hidden" name="capture_type" value="small_object" />
        <button className="btn primary" disabled={busy}>{busy ? "A criar…" : "Criar e escolher imagem"}<ArrowRight size={17} /></button>
      </form>
    </main>
  );
}
