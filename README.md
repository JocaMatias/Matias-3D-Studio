# Matias 3D Studio

Estúdio local para criar e comparar modelos 3D a partir de fotografias reais, referências geradas por IA ou uma combinação das duas. O objetivo é manter o fluxo utilizável com cinco imagens e aumentar a confiança à medida que são acrescentados ângulos realmente novos.

## O que está implementado

- projetos tipados como `fotografias reais`, `referências IA` ou `híbrido`;
- categorias genéricas para produtos, personagens, veículos, arquitetura e outros objetos;
- upload JPEG/PNG em streaming, verificação pelo conteúdo real, limites de tamanho e escrita atómica;
- seleção de uma imagem principal para ancorar referências de IA;
- validação de resolução, exposição, foco, duplicados, consistência visual e diversidade estimada;
- seleção automática entre IA multivista e COLMAP/OpenMVS conforme o tipo de projeto, cobertura e detalhe rastreável;
- vários candidatos de forma, seleção geométrica, limpeza e perfis de 25k/60k/120k faces;
- texturização UV com Hunyuan Paint quando o modelo está disponível, com fallback PBR explícito;
- versões imutáveis por reconstrução, versão principal e artefactos separados;
- fila Redis/RQ persistente no Docker e modo `thread` simples para desenvolvimento local;
- visualizador com textura, material sólido, wireframe, vistas, grelha, luz, rotação e ecrã inteiro;
- migrações Alembic compatíveis com a base antiga;
- diagnóstico de Python, RAM, disco, base de dados, armazenamento, GPU, fila e motor 3D;
- scripts Windows para iniciar, parar e instalar um atalho no ambiente de trabalho.

O triângulo `mock` continua apenas como fixture dos testes e nunca é apresentado como reconstrução real.

## Pipeline

1. Os originais são guardados por projeto e a orientação EXIF só é corrigida nas cópias de trabalho.
2. A validação separa qualidade técnica, consistência, cobertura e confiança. Estes valores são estimativas, não prova de geometria oculta.
3. A segmentação usa um método rápido em fundos uniformes e `rembg/u2netp` como fallback.
4. Com cinco vistas utilizáveis, Hunyuan3D multivista pode gerar vários candidatos. A referência principal ocupa a primeira câmara nos projetos IA/híbridos.
5. Fotografias reais com 20+ vistas e detalhe repetível podem seguir COLMAP/OpenMVS. Se o alinhamento falhar, o fallback generativo recebe uma confiança limitada pelo número real de câmaras recuperadas.
6. A melhor malha é limpa e simplificada conforme o perfil escolhido.
7. Hunyuan Paint tenta gerar uma textura UV multivista. Se não estiver instalado ou não couber na GPU, o resultado usa um material PBR uniforme e identifica claramente essa limitação.
8. Cada execução cria uma versão nova; resultados anteriores e a versão principal não são sobrescritos.

## Captura recomendada

Cinco imagens são um ponto de partida válido: frente, traseira, ambos os lados e uma vista superior oblíqua. Oito a doze vistas dão melhor cobertura a cavidades, ligações finas e zonas ocultas. Imagens repetidas não substituem ângulos novos.

- usa luz suave e constante, sem flash;
- mantém distância, zoom, orientação e estado do objeto;
- escolhe um fundo simples, mate e contrastante;
- em referências de IA, preserva exatamente proporções, materiais e detalhes;
- objetos transparentes, espelhados ou muito brilhantes continuam a exigir preparação especial.

O guia completo está em `/capture-guide`.

## Estrutura e dados

- `frontend/`: Next.js 14, TypeScript e React Three Fiber;
- `backend/`: FastAPI, SQLAlchemy, Alembic, Pillow, rembg, trimesh, Redis/RQ;
- `backend/storage/`: originais, miniaturas, máscaras, workspaces e artefactos;
- `backend/studio.db`: base SQLite local com projetos e versões;
- `backend/alembic/`: histórico de migrações;
- `tools/`: motores e modelos locais, ignorados pelo Git;
- `desktop/`: iniciador Windows e ícone.

Para consultar a base local, usa uma ferramenta SQLite como DB Browser for SQLite e abre `backend/studio.db` com o estúdio parado. Os ficheiros pesados não vivem na base: são guardados em `backend/storage/` e referenciados por caminho.

## Instalação local

Requisitos: Node.js 20+, Python 3.11+ e, para Hunyuan3D, uma GPU NVIDIA compatível com CUDA. A texturização pode necessitar mais VRAM do que a geração de forma; se falhar, o fallback PBR mantém o modelo utilizável.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
cd frontend
npm install
```

Início manual, em dois terminais:

```powershell
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

```powershell
cd frontend
npm run dev
```

Ou executa `desktop\Matias 3D Studio.bat`. Para criar o atalho, executa uma vez `desktop\install-desktop-shortcut.ps1`.

Interface: `http://localhost:3000`

API: `http://localhost:8000/docs`

## Migrações e fila

O arranque da API aplica migrações Alembic automaticamente. Também podem ser executadas manualmente:

```powershell
cd backend
python -m alembic upgrade head
```

O modo local predefinido usa `QUEUE_MODE=thread`. Para trabalhos persistentes, inicia Redis, define `QUEUE_MODE=rq` e executa:

```powershell
cd backend
python -m app.worker
```

O `docker-compose.yml` já usa Redis/RQ no backend e no worker; não contém um worker fictício.

## Diagnóstico e verificação

```powershell
cd backend
python -m app.diagnostics
python -m pytest -q

cd ..\frontend
npm run build
```

O mesmo diagnóstico está disponível em `GET /api/system/diagnostics`.

## Limitações honestas

- cinco vistas podem produzir um objeto plausível, mas zonas não observadas continuam a ser inferidas;
- consistência visual entre referências não garante consistência estrutural perfeita;
- COLMAP precisa de detalhe repetível e sobreposição; um número elevado de imagens não corrige superfícies uniformes;
- a qualidade Meshy-like depende dos modelos Hunyuan disponíveis, VRAM, consistência das referências e tempo de processamento;
- texturas muito finas, transparência, metal espelhado e interiores profundos continuam a ser casos difíceis;
- os modelos Hunyuan3D estão sujeitos às respetivas licenças.
