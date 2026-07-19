import Link from "next/link";
import { Aperture, ArrowRight, CircleDot, Images, Layers3, Lightbulb, ScanLine, Sparkles } from "lucide-react";

const steps = [
  ["1", "Escolhe um fundo simples", "Usa um fundo mate e diferente da cor do objeto. Evita padrões que possam ser confundidos com a geometria."],
  ["2", "Ilumina sem reflexos", "Prefere duas luzes suaves e constantes. Desliga o flash; brilho especular e sombras duras dificultam a correspondência."],
  ["3", "Mantém a escala", "Não alteres o zoom. Move a câmara à volta do objeto e mantém-no completo e centrado em todas as vistas."],
  ["4", "Cobre a forma", "Com 1–4 imagens escolhe vistas complementares. Para 5–15 cobre frente, traseira, lados e topo. Com 20+ cria duas voltas sobrepostas."],
];

export default function CaptureGuide() {
  return (
    <main className="shell" style={{ paddingBottom: 70 }}>
      <header className="guide-hero">
        <h1>De uma boa referência a uma digitalização precisa.</h1>
        <p className="sub" style={{ fontSize: 18 }}>Escolhe o modo pela cobertura disponível. Ângulos realmente novos e consistentes valem mais do que imagens repetidas.</p>
        <div className="actions"><Link className="btn primary" href="/projects/new">Criar projeto <ArrowRight size={17} /></Link></div>
      </header>

      <section className="grid3 guide-section">
        <article className="card"><Sparkles color="var(--mint)" /><h3>IA Multivista · 1–4</h3><p className="sub">Uma vista já funciona; vistas opostas reduzem a geometria que precisa de ser inferida.</p></article>
        <article className="card"><Layers3 color="var(--mint)" /><h3>Reconstrução híbrida · 5–15</h3><p className="sub">A cobertura observada ancora a forma e as cores; a IA completa apenas as zonas ocultas.</p></article>
        <article className="card"><ScanLine color="var(--mint)" /><h3>Digitalização precisa · 20+</h3><p className="sub">Duas voltas sobrepostas permitem recuperar câmaras reais, detalhe denso e textura projetada.</p></article>
      </section>

      <section className="guide-section">
        <div className="eyebrow">Preparação</div>
        <h2 className="section-title">Uma captura previsível produz uma malha estável.</h2>
        <div className="grid3" style={{ gridTemplateColumns: "repeat(2, 1fr)" }}>
          {steps.map(([number, title, description]) => (
            <article className="card guide-step" key={number}>
              <span className="guide-number">{number}</span><div><h3 style={{ marginTop: 0 }}>{title}</h3><p className="sub">{description}</p></div>
            </article>
          ))}
        </div>
      </section>

      <section className="guide-section layout">
        <article className="card">
          <div className="eyebrow">Cobertura recomendada</div>
          <h2>O que muda quando adicionas imagens?</h2>
          <ul className="checklist">
            <li><strong>1–4 vistas:</strong>&nbsp;IA Multivista, com inferência explícita das superfícies ocultas.</li>
            <li><strong>5–15 vistas:</strong>&nbsp;reconstrução híbrida com melhor cobertura de cavidades e ligações.</li>
            <li><strong>20+ vistas:</strong>&nbsp;digitalização precisa com tentativa de alinhamento COLMAP/OpenMVS.</li>
            <li>Imagens repetidas não acrescentam cobertura; procura sempre um ângulo realmente novo.</li>
          </ul>
        </article>
        <div className="coverage-ring"><div style={{ textAlign: "center" }}><Images size={52} color="var(--mint)" /><strong style={{ display: "block", fontSize: 34 }}>360°</strong><span className="sub">em duas alturas</span></div></div>
      </section>

      <section className="grid3 guide-section">
        <article className="card"><Aperture color="var(--warning)" /><h3>Objetos brilhantes</h3><p className="sub">Difunde a luz e evita reflexos que mudam de posição. Em casos difíceis, um spray mate removível apropriado pode ajudar.</p></article>
        <article className="card"><CircleDot color="var(--warning)" /><h3>Objetos transparentes</h3><p className="sub">A reconstrução direta continua limitada. Usa marcadores temporários no exterior ou uma versão mate para capturar a forma.</p></article>
        <article className="card"><Lightbulb color="var(--warning)" /><h3>Superfícies sem textura</h3><p className="sub">A IA multivista é preferida à fotogrametria clássica, mas vistas claras da silhueta continuam essenciais.</p></article>
      </section>
    </main>
  );
}
