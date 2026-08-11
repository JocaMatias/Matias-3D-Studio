import Link from "next/link";
import { Aperture, ArrowRight, CircleDot, Image as ImageIcon, Lightbulb, ScanLine, Sparkles } from "lucide-react";

const steps = [
  ["1", "Escolhe um fundo simples", "Usa um fundo mate e diferente da cor do objeto. Evita padrões que possam ser confundidos com a geometria."],
  ["2", "Ilumina sem reflexos", "Prefere duas luzes suaves e constantes. Desliga o flash; brilho especular e sombras duras dificultam a correspondência."],
  ["3", "Mostra o objeto inteiro", "Mantém todas as extremidades dentro da fotografia, com margem suficiente e a vista mais reconhecível voltada para a câmara."],
  ["4", "Dá contexto no nome", "Um nome como “colher de aço” ou “caneca com pega” ajuda o modo automático a preservar ou fechar cavidades corretamente."],
];

export default function CaptureGuide() {
  return (
    <main className="shell" style={{ paddingBottom: 70 }}>
      <header className="guide-hero">
        <h1>Uma fotografia melhor produz um modelo 3D melhor.</h1>
        <p className="sub" style={{ fontSize: 18 }}>O estúdio trabalha agora num fluxo focado: uma referência principal, vários candidatos locais e seleção automática da melhor forma.</p>
        <div className="actions"><Link className="btn primary" href="/projects/new">Criar projeto <ArrowRight size={17} /></Link></div>
      </header>

      <section className="grid3 guide-section">
        <article className="card"><ImageIcon color="var(--mint)" /><h3>Uma referência limpa</h3><p className="sub">A silhueta define a forma. Fundo contrastante, objeto completo e pouco ruído dão a melhor base.</p></article>
        <article className="card"><Sparkles color="var(--mint)" /><h3>Vários candidatos</h3><p className="sub">SPAR3D gera alternativas e o Stable Fast 3D participa como comparação nos perfis equilibrado e alto.</p></article>
        <article className="card"><ScanLine color="var(--mint)" /><h3>Textura incorporada</h3><p className="sub">A cor do objeto fica embutida no GLB; quando o motor não a fornece, o Matias projeta a fotografia de referência.</p></article>
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
          <div className="eyebrow">Escolha do perfil</div>
          <h2>Quando deves sair do modo automático?</h2>
          <ul className="checklist">
            <li><strong>Compacto:</strong>&nbsp;objetos sólidos; fecha falsos buracos causados por reflexos.</li>
            <li><strong>Recipiente com pega:</strong>&nbsp;preserva aberturas reais em canecas, jarros e peças semelhantes.</li>
            <li><strong>Partes finas:</strong>&nbsp;protege hastes, garfos, armações e estruturas delicadas.</li>
            <li><strong>Várias peças/mecânico:</strong>&nbsp;aceita componentes separados que pertencem ao objeto.</li>
          </ul>
        </article>
        <div className="coverage-ring"><div style={{ textAlign: "center" }}><Sparkles size={52} color="var(--mint)" /><strong style={{ display: "block", fontSize: 34 }}>3D</strong><span className="sub">local e privado</span></div></div>
      </section>

      <section className="grid3 guide-section">
        <article className="card"><Aperture color="var(--warning)" /><h3>Objetos brilhantes</h3><p className="sub">Difunde a luz e evita reflexos que mudam de posição. Em casos difíceis, um spray mate removível apropriado pode ajudar.</p></article>
        <article className="card"><CircleDot color="var(--warning)" /><h3>Objetos transparentes</h3><p className="sub">A reconstrução direta continua limitada. Usa marcadores temporários no exterior ou uma versão mate para capturar a forma.</p></article>
        <article className="card"><Lightbulb color="var(--warning)" /><h3>Objetos brancos</h3><p className="sub">Usa um fundo escuro ou colorido. Branco sobre branco força a segmentação a adivinhar os limites.</p></article>
      </section>
    </main>
  );
}
