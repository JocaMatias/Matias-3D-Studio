import Link from "next/link";
import { Aperture, ArrowRight, Camera, CircleDot, Images, Lightbulb, ScanLine, Sparkles } from "lucide-react";

const steps = [
  ["1", "Escolhe um fundo simples", "Usa um fundo mate e diferente da cor do objeto. Evita padrões que possam ser confundidos com a geometria."],
  ["2", "Ilumina sem reflexos", "Prefere duas luzes suaves e constantes. Desliga o flash; brilho especular e sombras duras dificultam a correspondência."],
  ["3", "Mantém a escala", "Não alteres o zoom. Move a câmara à volta do objeto e mantém-no completo e centrado em todas as vistas."],
  ["4", "Cobre a forma", "Com cinco imagens inclui frente, traseira, ambos os lados e uma vista superior. Acrescenta ângulos intermédios para maior precisão."],
];

export default function CaptureGuide() {
  return (
    <main className="shell" style={{ paddingBottom: 70 }}>
      <header className="guide-hero">
        <h1>Cinco boas vistas para começar. Mais ângulos para aperfeiçoar.</h1>
        <p className="sub" style={{ fontSize: 18 }}>O estúdio adapta o motor ao material enviado. A qualidade depende mais da cobertura e consistência do que de um número rígido de fotografias.</p>
        <div className="actions"><Link className="btn primary" href="/projects/new">Criar projeto <ArrowRight size={17} /></Link></div>
      </header>

      <section className="grid3 guide-section">
        <article className="card"><Camera color="var(--mint)" /><h3>Fotografias reais</h3><p className="sub">Todas as vistas devem mostrar exatamente o mesmo objeto, iluminação e estado.</p></article>
        <article className="card"><Sparkles color="var(--mint)" /><h3>Referências de IA</h3><p className="sub">Escolhe uma imagem principal e confirma que detalhes, proporções e materiais não mudam entre vistas.</p></article>
        <article className="card"><ScanLine color="var(--mint)" /><h3>Modo híbrido</h3><p className="sub">As fotografias reais ancoram a geometria; as referências adicionais ajudam apenas nas zonas sem cobertura.</p></article>
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
            <li><strong>5 vistas:</strong>&nbsp;base utilizável para objetos simples e referências consistentes.</li>
            <li><strong>8–12 vistas:</strong>&nbsp;melhor leitura de saliências, cavidades e ligações finas.</li>
            <li><strong>16+ vistas:</strong>&nbsp;útil para objetos complexos, assimétricos ou com detalhes pequenos.</li>
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
