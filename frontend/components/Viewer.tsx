"use client";

import { Canvas } from "@react-three/fiber";
import { Center, ContactShadows, Environment, OrbitControls, useGLTF } from "@react-three/drei";
import { Suspense, useEffect } from "react";

function Model({ url }: { url: string }) {
  const { scene } = useGLTF(url);
  useEffect(() => {
    scene.traverse((node) => {
      if ("castShadow" in node) {
        node.castShadow = true;
        node.receiveShadow = true;
      }
    });
  }, [scene]);
  return <Center><primitive object={scene} /></Center>;
}

export default function Viewer({ url }: { url: string }) {
  return (
    <div className="viewer">
      <Canvas
        shadows
        camera={{ position: [3.2, 2.25, 5.2], fov: 38, near: 0.1, far: 100 }}
        gl={{ antialias: true, toneMappingExposure: 0.78 }}
      >
        <color attach="background" args={["#09110f"]} />
        <ambientLight intensity={0.55} />
        <directionalLight castShadow position={[4, 6, 5]} intensity={1.45} />
        <directionalLight position={[-4, 2, -3]} intensity={0.35} color="#9ee8d2" />
        <Suspense fallback={null}>
          <Model url={url} />
          <Environment preset="studio" environmentIntensity={0.65} />
        </Suspense>
        <ContactShadows position={[0, -1.22, 0]} opacity={0.42} scale={5} blur={2.4} far={3} />
        <OrbitControls
          makeDefault
          autoRotate
          autoRotateSpeed={0.55}
          minDistance={3.2}
          maxDistance={9}
          minPolarAngle={0.35}
          maxPolarAngle={Math.PI / 2.05}
        />
        <gridHelper args={[10, 20, "#234039", "#14221f"]} position={[0, -1.23, 0]} />
      </Canvas>
    </div>
  );
}
