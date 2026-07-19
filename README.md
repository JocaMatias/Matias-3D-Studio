# Matias 3D Studio

Estúdio local para criar, validar, comparar e exportar modelos 3D a partir de imagens. A aplicação apresenta apenas três modos de geração, cada um com limites, validação e estratégia próprios.

| Modo | Imagens | Estratégia |
| --- | ---: | --- |
| IA Multivista | 1–4 | Hunyuan3D gera vários candidatos, infere zonas ocultas e recupera automaticamente malhas estruturalmente frágeis. |
| Reconstrução híbrida | 5–15 | As vistas reais reforçam a seleção, a cobertura observada e a projeção de cor; a IA completa zonas não visíveis. |
| Digitalização precisa | 20+ | COLMAP/OpenMVS tenta recuperar câmaras, geometria densa e textura; se o alinhamento falhar, existe fallback generativo com confiança limitada. |

O intervalo 16–19 continua utilizável no modo híbrido, mas a interface recomenda chegar às 20 vistas para desbloquear a digitalização precisa.

## O que está implementado

- upload JPEG/PNG em streaming, verificação pela assinatura real e escrita atómica;
- validação de resolução, exposição, foco, duplicados, consistência e diversidade;
- segmentação rápida para fundos uniformes e `rembg/u2netp` como fallback;
- seleção automática de vistas complementares sem assumir que o primeiro upload é frontal;
- 2, 4 ou 6 candidatos conforme o perfil de qualidade;
- rejeição de planos parasitas, fragmentação excessiva e componentes principais fracas;
- perfis de 25k, 60k e 120k faces para preview, standard e alta qualidade;
- Hunyuan Paint para textura UV quando o runtime CUDA está completo;
- recuperação em cascata: soldadura e limpeza da malha, sementes adicionais e, como último recurso, um proxy volumétrico fechado marcado como estimado;
- projeção portátil de cores multivista quando o rasterizador nativo não está disponível;
- preservação comprovada de material/cor durante a normalização e exportação GLB;
- versões imutáveis, versão principal, métricas e artefactos separados;
- fila local, fila inline determinística para testes e Redis/RQ para trabalhos persistentes;
- migrações Alembic, incluindo conversão dos nomes antigos para os três modos atuais;
- visualizador com textura, sólido, wireframe, vistas, grelha, luz e ecrã inteiro;
- diagnóstico de base de dados, armazenamento, GPU, fila e motores 3D.

O triângulo `mock` é apenas uma fixture técnica e nunca é apresentado como reconstrução real.

## Texturização

O pipeline nunca usa uma fotografia retangular como material da malha.

1. Se Hunyuan Paint, os modelos locais e `custom_rasterizer` estiverem disponíveis, gera uma textura UV multivista.
2. Se esse runtime não estiver disponível ou exceder a VRAM, projeta cor das vistas selecionadas nos vértices e exporta-a no GLB.
3. Apenas se não existirem referências de cor válidas usa um material PBR uniforme.

Na RTX 5060 Laptop de 8 GB, a geração de forma funciona localmente. Hunyuan Paint pode exigir cerca de 16 GB e um runtime CUDA compilado; por isso, a projeção de cor é o fallback seguro para esse hardware.

## Estrutura e dados

- `frontend/`: Next.js 15, TypeScript e React Three Fiber;
- `backend/`: FastAPI, SQLAlchemy, Alembic, Pillow, rembg, trimesh e Redis/RQ;
- `backend/storage/`: originais, miniaturas, máscaras, workspaces e artefactos;
- `backend/studio.db`: base SQLite local com projetos, jobs e versões;
- `tools/`: motores e modelos locais ignorados pelo Git;
- `desktop/`: iniciador Windows e ícone.

Para consultar a base local, abre `backend/studio.db` com DB Browser for SQLite e com o estúdio parado. Os ficheiros pesados ficam em `backend/storage/`; a base guarda apenas os metadados e caminhos.

## Instalação local

Requisitos: Node.js 20+, Python 3.12–3.14 e uma GPU NVIDIA/CUDA para Hunyuan3D.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
cd frontend
npm ci
```

Início manual em dois terminais:

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

```powershell
cd frontend
npm run dev
```

Também podes executar `desktop\Matias 3D Studio.bat`. O iniciador reinicia serviços antigos do próprio Studio, confirma a versão da API e executa `npm ci` quando a versão local do Next.js não coincide com o lockfile. Para criar o atalho, executa uma vez `desktop\install-desktop-shortcut.ps1`.

Interface: `http://localhost:3000`
API: `http://localhost:8000/docs`

## Fila e testes

O desenvolvimento local usa `QUEUE_MODE=thread`. Os testes definem `QUEUE_MODE=inline`, `RECONSTRUCTION_MODE=mock`, uma base SQLite temporária e armazenamento temporário antes de importar a aplicação. Isto impede alterações na base real e torna regressões presas em `processing` determinísticas.

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q

cd ..\frontend
npm run build
npm audit --package-lock-only
```

## Docker Compose

O Compose arranca PostgreSQL, Redis, backend, worker RQ e frontend com healthchecks. Por omissão usa `RECONSTRUCTION_MODE=mock`, porque os modelos Hunyuan e executáveis Windows locais não fazem parte das imagens Linux.

```powershell
docker compose up --build
```

As portas podem ser isoladas sem editar o ficheiro:

```powershell
$env:FRONTEND_PORT = "3300"
$env:BACKEND_PORT = "8800"
docker compose -p matias3d-verify up --build
```

## Limitações honestas

- uma a quatro vistas podem produzir um objeto plausível, mas zonas não observadas são inferidas;
- cinco a quinze vistas melhoram cobertura e seleção, mas não substituem câmaras reais recuperadas;
- COLMAP precisa de detalhe repetível e sobreposição; muitas imagens não corrigem superfícies lisas, transparentes ou espelhadas;
- quatro referências geradas por IA de um objeto complexo só funcionam bem se forma, proporções e detalhes forem consistentes entre vistas;
- a qualidade Meshy-like depende do modelo generativo, VRAM, consistência das referências e tempo disponível;
- os modelos Hunyuan3D estão sujeitos às respetivas licenças.
