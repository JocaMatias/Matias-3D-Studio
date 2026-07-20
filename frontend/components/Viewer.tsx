"use client";

import { Canvas, useThree } from "@react-three/fiber";
import { Center, ContactShadows, Environment, OrbitControls, useGLTF } from "@react-three/drei";
import { Box, Expand, Grid3X3, Image as ImageIcon, Pause, Play, RotateCcw, Sun, Triangle } from "lucide-react";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";

type ViewMode = "textured" | "solid" | "wireframe";
type CameraView = "perspective" | "front" | "back" | "left" | "right" | "top" | "bottom";

function Model({ url, mode }: { url: string; mode: ViewMode }) {
  const { scene } = useGLTF(url);
  const originals = useRef(new Map<string, THREE.Material | THREE.Material[]>());
  const override = useMemo(() => new THREE.MeshStandardMaterial({
    color: mode === "wireframe" ? "#4ee4bd" : "#dfe9e6",
    roughness: 0.64,
    metalness: 0.03,
    wireframe: mode === "wireframe",
  }), [mode]);

  useEffect(() => {
    scene.traverse((node) => {
      if (!(node instanceof THREE.Mesh)) return;
      node.castShadow = true;
      node.receiveShadow = true;
      if (!originals.current.has(node.uuid)) originals.current.set(node.uuid, node.material);
      node.material = mode === "textured" ? originals.current.get(node.uuid)! : override;
    });
    return () => {
      scene.traverse((node) => {
        if (node instanceof THREE.Mesh && originals.current.has(node.uuid)) node.material = originals.current.get(node.uuid)!;
      });
      override.dispose();
    };
  }, [mode, override, scene]);

  return <Center><primitive object={scene} /></Center>;
}

function CameraPosition({ view }: { view: CameraView }) {
  const { camera } = useThree();
  useEffect(() => {
    const positions: Record<CameraView, [number, number, number]> = {
      perspective: [3.2, 2.25, 5.2],
      front: [0, 0.4, 5.8],
      back: [0, 0.4, -5.8],
      left: [-5.8, 0.4, 0],
      right: [5.8, 0.4, 0],
      top: [0.001, 6.2, 0.001],
      bottom: [0.001, -6.2, 0.001],
    };
    camera.position.set(...positions[view]);
    camera.lookAt(0, 0, 0);
    camera.updateProjectionMatrix();
  }, [camera, view]);
  return null;
}

export default function Viewer({
  url,
  hasTexture = true,
  hasVertexColors = false,
}: {
  url: string;
  hasTexture?: boolean;
  hasVertexColors?: boolean;
}) {
  const root = useRef<HTMLDivElement>(null);
  const canShowOriginal = hasTexture || hasVertexColors;
  const [mode, setMode] = useState<ViewMode>(canShowOriginal ? "textured" : "solid");
  const [view, setView] = useState<CameraView>("perspective");
  const [grid, setGrid] = useState(true);
  const [rotate, setRotate] = useState(true);
  const [light, setLight] = useState(1);
  const [background, setBackground] = useState<"dark" | "light">("dark");

  useEffect(() => {
    if (!canShowOriginal && mode === "textured") setMode("solid");
  }, [canShowOriginal, mode]);

  async function fullscreen() {
    if (!document.fullscreenElement) await root.current?.requestFullscreen();
    else await document.exitFullscreen();
  }

  return (
    <div className="viewer" ref={root}>
      <div className="viewer-toolbar" aria-label="Ferramentas do visualizador 3D">
        <button className={`viewer-button ${mode === "textured" ? "active" : ""}`} disabled={!canShowOriginal} onClick={() => setMode("textured")} title={canShowOriginal ? (hasTexture ? "Texturizado" : "Cores por vértice") : "Textura indisponível nesta versão"}><ImageIcon size={16} /> {hasTexture ? "Textura" : hasVertexColors ? "Cores" : "Sem textura"}</button>
        <button className={`viewer-button ${mode === "solid" ? "active" : ""}`} onClick={() => setMode("solid")} title="Material sólido"><Box size={16} /> Sólido</button>
        <button className={`viewer-button ${mode === "wireframe" ? "active" : ""}`} onClick={() => setMode("wireframe")} title="Wireframe"><Triangle size={16} /> Malha</button>
        <button className="viewer-button" onClick={() => setView("perspective")} title="Perspetiva"><RotateCcw size={16} /></button>
        <button className="viewer-button" onClick={() => setView("front")}>Frente</button>
        <button className="viewer-button" onClick={() => setView("back")}>Trás</button>
        <button className="viewer-button" onClick={() => setView("left")}>Esq.</button>
        <button className="viewer-button" onClick={() => setView("right")}>Dir.</button>
        <button className="viewer-button" onClick={() => setView("top")}>Topo</button>
        <button className="viewer-button" onClick={() => setView("bottom")}>Base</button>
        <button className={`viewer-button ${grid ? "active" : ""}`} onClick={() => setGrid((value) => !value)} title="Mostrar grelha"><Grid3X3 size={16} /></button>
        <button className={`viewer-button ${rotate ? "active" : ""}`} onClick={() => setRotate((value) => !value)} title="Rotação automática">{rotate ? <Pause size={16} /> : <Play size={16} />}</button>
        <button className="viewer-button" onClick={() => setBackground((value) => value === "dark" ? "light" : "dark")} title="Alternar fundo"><Sun size={16} /></button>
        <label className="viewer-button" title="Intensidade da luz" style={{ display: "inline-flex", alignItems: "center", gap: 7 }}><Sun size={15} /><input type="range" min="0.35" max="1.7" step="0.05" value={light} onChange={(event) => setLight(Number(event.target.value))} /></label>
        <button className="viewer-button" onClick={() => void fullscreen()} title="Ecrã inteiro" style={{ marginLeft: "auto" }}><Expand size={16} /></button>
      </div>
      <Canvas shadows camera={{ position: [3.2, 2.25, 5.2], fov: 38, near: 0.1, far: 100 }} gl={{ antialias: true, toneMappingExposure: 0.86 }}>
        <color attach="background" args={[background === "dark" ? "#060d0c" : "#cfd8d5"]} />
        <CameraPosition view={view} />
        <ambientLight intensity={0.46 * light} />
        <directionalLight castShadow position={[4, 6, 5]} intensity={1.35 * light} />
        <directionalLight position={[-4, 2, -3]} intensity={0.32 * light} color="#9ee8d2" />
        <Suspense fallback={null}>
          <Model url={url} mode={mode} />
          <Environment preset="studio" environmentIntensity={0.6 * light} />
        </Suspense>
        <ContactShadows position={[0, -1.22, 0]} opacity={0.4} scale={5} blur={2.4} far={3} />
        <OrbitControls makeDefault autoRotate={rotate} autoRotateSpeed={0.55} minDistance={2.2} maxDistance={12} minPolarAngle={0.08} maxPolarAngle={Math.PI - 0.08} />
        {grid && <gridHelper args={[10, 20, "#2d5149", "#152622"]} position={[0, -1.23, 0]} />}
      </Canvas>
    </div>
  );
}
