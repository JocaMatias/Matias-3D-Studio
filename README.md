# Matias 3D Studio

Estúdio local para criar, validar, comparar e exportar modelos 3D. A interface separa claramente dois objetivos diferentes:

| Modo | Estado | Entrada | Resultado |
| --- | --- | --- | --- |
| **Criar com IA** | Disponível | Uma imagem principal | Modelo plausível com as zonas invisíveis estimadas localmente por IA |
| **Digitalizar objeto real** | Em desenvolvimento | Muitas fotografias reais | Reconstrução fotogramétrica baseada no objeto físico |

O modo principal atual funciona sem créditos por geração: usa a GPU NVIDIA do computador e guarda os modelos e pesos localmente.

## Criar com IA

O pipeline foi redesenhado para não fundir várias referências contraditórias. Usa uma única imagem principal como âncora:

```text
Imagem principal
→ validação e segmentação
→ SPAR3D Low VRAM
→ candidatos sequenciais
→ comparação de silhueta e integridade
→ Stable Fast 3D se necessário
→ seleção do melhor GLB
→ controlo de qualidade
→ nova versão no projeto
```

### Motores locais

- **SPAR3D Low VRAM:** motor principal para a GPU NVIDIA de 8 GB.
- **Stable Fast 3D:** fallback local quando o SPAR3D falha ou produz um candidato fraco.

Os dois motores são instalados em ambientes Python separados dentro da distro WSL2 isolada `MatiasAI`. Não entram no Git e não interferem com as dependências do backend Windows.

### Perfis de geração

- **Rápido:** um candidato, textura 512 px.
- **Equilibrado:** dois candidatos sequenciais, textura 1024 px.
- **Alta qualidade:** três candidatos sequenciais, textura 2048 px.

Para 8 GB de VRAM, começa por **Rápido** e só depois experimenta **Equilibrado**. Os candidatos são executados um de cada vez para libertar memória entre gerações.

## Instalação base

Requisitos da aplicação:

- Node.js 20+;
- Python para o backend;
- Git.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
cd frontend
npm ci
cd ..
```

## Instalar os motores locais

Os motores exigem adicionalmente:

- Windows 11 com WSL2;
- GPU NVIDIA e driver compatível com CUDA no WSL;
- conta Hugging Face, acesso aceite aos modelos e token `Read`.

Na raiz do projeto:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
& ".\desktop\install-local-ai-engines.ps1"
```

O instalador retomável cria/reutiliza a distro `MatiasAI`, fixa as revisões e dependências, descarrega os pesos sem guardar o token, valida os dois motores e gera GLBs reais de smoke test. Os motores nunca são compilados com MSVC no Windows.

Mais detalhes: [`docs/local-ai.md`](docs/local-ai.md).

## Iniciar

```powershell
& ".\desktop\Matias 3D Studio.bat"
```

Ou manualmente em dois terminais:

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

```powershell
cd frontend
npm run dev
```

Interface: `http://localhost:3000`
API: `http://localhost:8000/docs`

## O que está implementado

- upload JPEG/PNG em streaming com verificação do conteúdo real;
- imagem principal explícita;
- perfis de objeto: automático, compacto, partes finas, várias peças, recipiente com pega, mecânico, orgânico e arquitetura;
- segmentação e entrada PNG com alpha verdadeiro;
- geração local single-image-to-3D;
- vários candidatos sequenciais no SPAR3D;
- fallback Stable Fast 3D;
- seleção automática por silhueta, componente principal, fragmentação e materiais;
- distinção entre textura UV, cores por vértice, material uniforme e ausência de material;
- métricas finais separadas das métricas da imagem de entrada;
- versões imutáveis e relatório JSON dos candidatos;
- viewer com textura/cores apenas quando disponíveis, sólido, wireframe e sete vistas;
- fila local, fila inline para testes e Redis/RQ;
- migrations Alembic;
- Docker sem dependência do output `standalone` do Next.js, evitando o bloqueio Windows em `Collecting build traces`.

## Testes

```powershell
$env:PYTHONPATH = "backend"
python -m pytest -q

cd frontend
& ".\node_modules\.bin\tsc.cmd" --noEmit
npm run build
```

## Docker Compose

O Compose continua útil para validar frontend, backend, PostgreSQL, Redis e worker. Os motores NVIDIA locais de Windows não são incluídos nas imagens Docker.

```powershell
docker compose up --build
```

## Digitalizar objeto real

A opção aparece como **Em desenvolvimento**. Quando for retomada, usará um pipeline separado de fotogrametria com COLMAP/OpenMVS. Não será misturada com a geração por IA e não substituirá silenciosamente zonas observadas por geometria inventada.

## Limitações honestas

- Uma imagem não contém informação sobre a traseira; essas zonas são inferidas.
- Objetos transparentes, espelhados, muito finos ou mecanicamente complexos continuam difíceis.
- O resultado pode ser visualmente convincente sem ser uma cópia métrica do objeto.
- Os motores dependem do suporte WSL2/CUDA do driver NVIDIA instalado no Windows.
- A qualidade não é garantida como igual à de serviços comerciais proprietários.
- Confirma a licença dos modelos antes de distribuição comercial; o funcionamento local não elimina obrigações de licença.
