"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Sparkles } from "lucide-react";
import { Project, request } from "@/lib/api";

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
        body: JSON.stringify({ ...Object.fromEntries(form), project_type: "ai_generation" }),
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
        <div className="row" style={{ justifyContent: "flex-start", gap: 10 }}>
          <Sparkles size={23} color="var(--mint)" />
          <span className="eyebrow">GEOMETRIA ASSISTIDA POR IA</span>
        </div>
        <h1>Transforma uma fotografia num modelo 3D.</h1>
        <p className="sub">O Matias isola o objeto, gera vários candidatos localmente, compara a forma e incorpora a referência como textura PBR.</p>
        {error && <p className="error">{error}</p>}

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
          <span className="sub">Automático reconhece casos comuns pelo nome. Escolhe manualmente apenas quando existem cavidades reais, pegas ou várias peças.</span>
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
        <button className="btn primary" disabled={busy}>{busy ? "A preparar o estúdio…" : "Continuar para a fotografia"}<ArrowRight size={17} /></button>
      </form>
    </main>
  );
}
