# ImageTo3D Studio

MVP web de reconstrução 3D real a partir de fotografias, criado em `Documents/3D Simulator`.

O sistema inclui projetos, upload em lote, validação técnica, segmentação do objeto, geração multivista com Hunyuan3D, refinamento opcional com COLMAP/OpenMVS, progresso por etapas, visualizador 3D e exportação GLB. O antigo triângulo de demonstração continua disponível apenas para testes automatizados e nunca é mostrado como resultado real.

## Pipeline real

1. Corrige a orientação EXIF e preserva os originais.
2. Deteta imagens desfocadas, flash/reflexos, exposição e duplicados próximos.
3. Isola o objeto do fundo com uma máscara rápida para fundos uniformes e `rembg/u2netp` como fallback local.
4. Com 5–10 imagens, ordena semanticamente frente/esquerda/traseira/direita e rejeita vistas invertidas ou demasiado superiores.
5. O Hunyuan3D-2mv gera quatro candidatos de forma; proporções, validade da malha e características topológicas visíveis (por exemplo, uma pega) decidem o vencedor.
6. Aplica um material PBR coerente e sem sombras fotográficas coladas à geometria.
7. Reduz a malha vencedora para cerca de 60 mil triângulos e exporta um GLB leve para visualização em tempo real.
8. Só com 20+ imagens **e** detalhe visual repetível tenta o modo híbrido COLMAP/OpenMVS; superfícies lisas continuam na IA em vez de falharem o alinhamento.

Uma reconstrução é desbloqueada com 5 imagens utilizáveis. Cinco vistas já produzem um resultado plausível; 8–10 vistas complementares dão à seleção mais hipóteses de preservar pegas, cavidades, base e traseira. A interface separa `fidelidade visual` de `confiança geométrica` e usa estimativas conservadoras: fotografias tecnicamente perfeitas não são tratadas como prova de superfícies que não aparecem nelas.

## Captura recomendada

Para objetos pequenos começa com 5–10 fotografias:

- luz suave e difusa, sem flash;
- zoom, foco e distância constantes;
- frente, traseira, lados e uma vista ligeiramente superior;
- objeto completo, centrado e com escala semelhante em todas as vistas;
- fotografias adicionais de cavidades, pegas e zonas ocultas melhoram progressivamente o resultado;
- com 20+ vistas ordenadas à volta do objeto, o sistema tenta também fotogrametria de alta precisão;
- em porcelana branca ou brilhante, iluminação polarizada/difusa e marcadores removíveis ajudam muito.

As 13 fotografias da chávena deixam de ser bloqueadas: entram no modo `IA multivista reforçada`. O sistema continua a avisar que flash e porcelana brilhante reduzem a confiança geométrica, sem exigir uma sessão fotogramétrica perfeita.

## Arquitetura

- `frontend/`: Next.js 14, TypeScript, React Three Fiber.
- `backend/`: FastAPI, SQLAlchemy, Pillow, rembg e trimesh.
- `backend/storage/`: originais, thumbnails, máscaras, workspaces e artefactos por projeto.
- `tools/COLMAP-4.0.1/`: COLMAP CUDA com os modelos ALIKED/LightGlue.
- `tools/OpenMVS-2.4/`: OpenMVS para densificação, mesh e textura.
- `tools/Hunyuan3D-2/`: motor generativo multivista oficial.
- `tools/hunyuan-env/`: Python 3.10/CUDA isolado para a IA.
- `scripts/reconstruct_project.py`: execução síncrona de diagnóstico.

Os binários em `tools/`, modelos ONNX, dados de execução e bases SQLite estão ignorados pelo Git.

## Início local

Requisitos: Node.js 20+, Python 3.11+ para a API e GPU NVIDIA com cerca de 6 GB de VRAM para a IA local.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
cd frontend
npm install
```

Terminal 1, a partir da raiz:

```powershell
uvicorn backend.app.main:app --reload --port 8000
```

Terminal 2:

```powershell
cd frontend
npm run dev
```

Abre `http://localhost:3000`. A API fica em `http://localhost:8000/docs`.

## Configuração

As predefinições locais já apontam para os motores instalados. Para personalizar, copia `.env.example` para `.env`.

```dotenv
RECONSTRUCTION_MODE=colmap
COLMAP_ROOT=./tools/COLMAP-4.0.1
OPENMVS_ROOT=./tools/OpenMVS-2.4
HUNYUAN_ROOT=./tools/Hunyuan3D-2
HUNYUAN_PYTHON=./tools/hunyuan-env/python.exe
SEGMENTATION_MODEL=u2netp
ENABLE_OBJECT_SEGMENTATION=true
```

`RECONSTRUCTION_MODE=mock` existe apenas para desenvolvimento e testes; os artefactos ficam marcados como `simulated` e `displayable: false`.

## Verificação

```powershell
python -m pytest backend\tests -q
cd frontend
npm run build
```

## Limitações

- Fotogrametria não recupera detalhe que não aparece com sobreposição em várias fotos.
- A IA consegue preencher zonas ocultas, mas essas zonas são estimativas plausíveis e não medições.
- O modo local aproxima a experiência de serviços comerciais através de seleção multivista, vários candidatos e otimização; não inclui ainda um modelo generativo dedicado de texturas PBR, por isso padrões complexos devem ser tratados numa fase de texturização posterior.
- O modelo Hunyuan3D está sujeito à respetiva licença comunitária/não comercial da Tencent.
- Objetos transparentes, espelhados, muito brilhantes ou sem textura exigem preparação de estúdio.
- O job local usa uma thread de background e não sobrevive a reinícios; produção deve usar Celery/RQ.
- O `docker-compose.yml` não inclui os binários GPU de COLMAP/OpenMVS; o pipeline real está preparado para execução Windows local.
