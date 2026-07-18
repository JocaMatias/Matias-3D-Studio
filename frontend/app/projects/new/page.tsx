"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Camera, Layers3, Sparkles } from "lucide-react";
import { Project, ProjectType, request } from "@/lib/api";

const choices: { value: ProjectType; title: string; description: string; icon: typeof Camera }[] = [
  { value: "real_photos", title: "Fotografias reais", description: "Vistas do mesmo objeto físico, captadas à sua volta.", icon: Camera },
  { value: "ai_references", title: "Referências de IA", description: "Imagens consistentes do mesmo conceito; escolhe uma vista principal.", icon: Sparkles },
  { value: "hybrid", title: "Modo híbrido", description: "Combina fotografias reais com referências que completam zonas ocultas.", icon: Layers3 },
];

export default function NewProject() {
  const router = useRouter();
  const [projectType, setProjectType] = useState<ProjectType>("real_photos");
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
        <h1>O que vamos modelar?</h1>
        <p className="sub">Define a origem das imagens para o motor escolher a estratégia mais adequada.</p>
        {error && <p className="error">{error}</p>}

        <div className="field">
          <label>Nome do projeto</label>
          <input className="input" name="name" required minLength={2} placeholder="Ex.: Avião antigo" />
        </div>
        <div className="field">
          <label>Descrição opcional</label>
          <textarea className="input" name="description" rows={3} placeholder="Material, escala, detalhes importantes ou objetivo do modelo" />
        </div>
        <div className="field">
          <label>Origem das imagens</label>
          <div className="choice-grid">
            {choices.map((choice) => {
              const Icon = choice.icon;
              return (
                <button className={`choice ${projectType === choice.value ? "active" : ""}`} type="button" key={choice.value} onClick={() => setProjectType(choice.value)}>
                  <Icon size={22} color="var(--mint)" />
                  <strong style={{ display: "block", margin: "10px 0 5px", color: "var(--text)" }}>{choice.title}</strong>
                  <span className="sub" style={{ fontSize: 12 }}>{choice.description}</span>
                </button>
              );
            })}
          </div>
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
        <div className="field">
          <label>Escala da captura</label>
          <select className="input" name="capture_type" defaultValue="small_object">
            <option value="small_object">Objeto pequeno</option>
            <option value="medium_object">Objeto médio</option>
            <option value="environment">Espaço ou ambiente</option>
          </select>
        </div>
        <button className="btn primary" disabled={busy}>{busy ? "A criar…" : "Criar e adicionar imagens"}<ArrowRight size={17} /></button>
      </form>
    </main>
  );
}
