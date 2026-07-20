# Geração local com IA

O modo **Criar com IA** usa uma única imagem principal. A geometria invisível é estimada; não é uma medição física.

## Motores

1. **SPAR3D Low VRAM** — motor principal em GPUs NVIDIA de 8 GB.
2. **Stable Fast 3D** — fallback quando o SPAR3D não produz um candidato utilizável ou fica sem memória.

Cada motor vive num ambiente Python próprio dentro de `/opt/matias-ai` na distro WSL2 isolada `MatiasAI`, evitando conflitos com o backend Windows. Os pesos ficam no cache local da mesma distro.

## Instalação

Requisitos externos:

- Windows 11 com WSL2;
- GPU NVIDIA com driver atualizado;
- Git;
- conta Hugging Face, aceitação das condições dos dois modelos e token com permissão `Read`.

Executar na raiz do projeto:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
& ".\desktop\install-local-ai-engines.ps1"
```

O script fixa revisões dos repositórios oficiais, cria ambientes isolados, instala PyTorch CUDA 13.2 e dependências versionadas e descarrega os pesos. O token é recebido apenas por stdin durante o download e não é guardado no projeto, `.env`, Git, frontend ou cache após a instalação.

O instalador é retomável: etapas já válidas são reutilizadas e os smoke tests só são repetidos quando o worker muda. `-Offline` força a utilização exclusiva dos pesos já presentes no cache; `-ResetDistro` recria a distro apenas quando pedido explicitamente.

## Perfis

- **Rápido:** um candidato, textura 512 px.
- **Equilibrado:** dois candidatos sequenciais, textura 1024 px.
- **Alta qualidade:** três candidatos sequenciais, textura 2048 px.

Com 8 GB de VRAM, começa pelo perfil Rápido. Fecha jogos, navegadores com aceleração 3D e outras aplicações CUDA antes de gerar.

## Fluxo

1. O Studio valida e segmenta a imagem principal.
2. Cria um PNG com alpha verdadeiro e enquadramento quadrado.
3. SPAR3D gera candidatos sequencialmente com seeds diferentes.
4. Cada GLB é analisado quanto a silhueta, fragmentação, componente principal e materiais.
5. O melhor candidato é normalizado e guardado como nova versão.
6. Se o SPAR3D falhar, o Stable Fast 3D é usado como fallback.

## Limitações

- A traseira e as zonas ocultas são inferidas.
- Objetos finos, transparentes, espelhados ou muito complexos continuam difíceis.
- A qualidade não é garantida como equivalente a serviços comerciais proprietários.
- A execução dos motores exige que a GPU CUDA esteja acessível dentro da distro `MatiasAI`.
- Os modelos estão sujeitos à Stability AI Community License; confirma as condições antes de distribuição comercial.
