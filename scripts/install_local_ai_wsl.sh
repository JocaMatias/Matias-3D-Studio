#!/usr/bin/env bash
set -Eeuo pipefail

WORKER_SOURCE="${1:?worker path is required}"
OFFLINE="${2:-0}"
ROOT=/opt/matias-ai
CACHE="$ROOT/model-cache"
SPAR_REPO="$ROOT/stable-point-aware-3d"
SF3D_REPO="$ROOT/stable-fast-3d"
SPAR_ENV="$ROOT/spar3d-env"
SF3D_ENV="$ROOT/sf3d-env"
SPAR_COMMIT=fdc311b16809e6a8adc2f5a3407ebb3db1a95bd1
SF3D_COMMIT=ff21fc491b4dc5314bf6734c7c0dabd86b5f5bb2
TORCH_VERSION=2.12.1
TORCHVISION_VERSION=0.27.1
TORCH_INDEX=https://download.pytorch.org/whl/cu132

export DEBIAN_FRONTEND=noninteractive
export PIP_DISABLE_PIP_VERSION_CHECK=1
export HF_HOME="$CACHE"
export ALPHA_CLIP_PATH="$CACHE/alpha-clip"
export NO_ALBUMENTATIONS_UPDATE=1
export TORCH_CUDA_ARCH_LIST=12.0
export MAX_JOBS=1
export CMAKE_BUILD_PARALLEL_LEVEL=1
export USE_CUDA=1
export CUDA_HOME=/usr/local/cuda-13.2
export PATH="$CUDA_HOME/bin:/usr/lib/wsl/lib:$PATH"
export LD_LIBRARY_PATH="$CUDA_HOME/lib64:/usr/lib/wsl/lib:${LD_LIBRARY_PATH:-}"

log() { printf '\n==> %s\n' "$1"; }

retry() {
    local attempt=1
    local delay=8
    until "$@"; do
        if (( attempt >= 4 )); then return 1; fi
        printf 'Tentativa %d falhou; repetir em %ds...\n' "$attempt" "$delay"
        sleep "$delay"
        attempt=$((attempt + 1))
        delay=$((delay * 2))
    done
}

mkdir -p "$ROOT" "$CACHE" "$ALPHA_CLIP_PATH"
IFS= read -r PROVIDED_TOKEN || true
PROVIDED_TOKEN="${PROVIDED_TOKEN%$'\r'}"
export HF_TOKEN="${PROVIDED_TOKEN:-${HF_TOKEN:-}}"
if [[ -z "$HF_TOKEN" && -s "$CACHE/token" ]]; then
    HF_TOKEN="$(<"$CACHE/token")"
    export HF_TOKEN
fi
cleanup_token() {
    unset HF_TOKEN PROVIDED_TOKEN
    rm -f "$CACHE/token"
}
trap cleanup_token EXIT

if ! command -v git >/dev/null || ! command -v cmake >/dev/null || ! command -v nvcc >/dev/null; then
    log "Instalar ferramentas Linux e CUDA 13.2"
    retry apt-get update
    retry apt-get install -y ca-certificates curl git build-essential pkg-config python3 python3-venv python3-pip ninja-build cmake libgl1 libglib2.0-0 libgomp1
    if ! command -v nvcc >/dev/null; then
        if ! dpkg -s cuda-keyring >/dev/null 2>&1; then
            retry curl -fsSL https://developer.download.nvidia.com/compute/cuda/repos/wsl-ubuntu/x86_64/cuda-keyring_1.1-1_all.deb -o /tmp/cuda-keyring.deb
            dpkg -i /tmp/cuda-keyring.deb
        fi
        retry apt-get update
        retry apt-get install -y cuda-toolkit-13-2
    fi
fi
log "Validar WSL, compilador CUDA e GPU"
nvcc --version
if command -v nvidia-smi >/dev/null; then nvidia-smi; else /usr/lib/wsl/lib/nvidia-smi; fi

ensure_repo() {
    local url="$1" destination="$2" commit="$3"
    if [[ ! -d "$destination/.git" ]]; then
        retry git clone "$url" "$destination"
    fi
    local current
    current="$(git -C "$destination" rev-parse HEAD)"
    if [[ "$current" != "$commit" ]]; then
        if ! git -C "$destination" diff --quiet || ! git -C "$destination" diff --cached --quiet; then
            echo "O repositório gerido tem alterações locais: $destination" >&2
            return 1
        fi
        retry git -C "$destination" fetch origin "$commit"
        git -C "$destination" checkout --detach "$commit"
    fi
}

log "Fixar revisões dos motores"
ensure_repo https://github.com/Stability-AI/stable-point-aware-3d.git "$SPAR_REPO" "$SPAR_COMMIT"
ensure_repo https://github.com/Stability-AI/stable-fast-3d.git "$SF3D_REPO" "$SF3D_COMMIT"
install -m 0644 "$WORKER_SOURCE" "$ROOT/local_ai_worker.py"

ensure_torch() {
    local venv="$1"
    if [[ ! -x "$venv/bin/python" ]]; then python3 -m venv "$venv"; fi
    if ! "$venv/bin/python" - <<'PY' 2>/dev/null
from importlib.metadata import version
expected = {"pip": "26.1.1", "setuptools": "69.5.1", "wheel": "0.45.1", "packaging": "24.2"}
raise SystemExit(0 if all(version(name) == value for name, value in expected.items()) else 1)
PY
    then
        "$venv/bin/python" -m pip install --upgrade pip==26.1.1 setuptools==69.5.1 wheel==0.45.1 packaging==24.2
    fi
    if ! "$venv/bin/python" -c "import torch, sys; sys.exit(0 if torch.__version__.startswith('${TORCH_VERSION}+cu132') else 1)" 2>/dev/null; then
        retry "$venv/bin/python" -m pip install --upgrade "torch==$TORCH_VERSION" "torchvision==$TORCHVISION_VERSION" --index-url "$TORCH_INDEX"
    fi
}

install_requirements() {
    local name="$1" repo="$2" venv="$3" extra_pin="$4"
    ensure_torch "$venv"
    local fingerprint stamp repo_revision requirements_hash
    repo_revision="$(git -C "$repo" rev-parse HEAD)"
    requirements_hash="$(sha256sum "$repo/requirements.txt" | cut -d' ' -f1)"
    fingerprint="$repo_revision-$requirements_hash-$TORCH_VERSION-$TORCHVISION_VERSION-$extra_pin"
    stamp="$venv/.matias-requirements"
    if [[ ! -f "$stamp" || "$(<"$stamp")" != "$fingerprint" ]]; then
        log "Instalar dependências fixas de $name"
        (
            cd "$repo"
            retry env USE_CUDA=1 TORCH_CUDA_ARCH_LIST=12.0 MAX_JOBS=1 "$venv/bin/python" -m pip install --no-build-isolation -r requirements.txt
        )
        if [[ -n "$extra_pin" ]]; then
            "$venv/bin/python" -m pip install "$extra_pin" packaging==24.2
        fi
        "$venv/bin/python" -m pip check
        printf '%s' "$fingerprint" > "$stamp"
    fi
}

install_requirements "SPAR3D Low VRAM" "$SPAR_REPO" "$SPAR_ENV" "flet==0.25.2"
if ! "$SPAR_ENV/bin/python" -c "import gpytoolbox, pynanoinstantmeshes" 2>/dev/null; then
    log "Instalar remalhagem oficial do SPAR3D"
    (
        cd "$SPAR_REPO"
        retry "$SPAR_ENV/bin/python" -m pip install -r requirements-remesh.txt
    )
fi
install_requirements "Stable Fast 3D" "$SF3D_REPO" "$SF3D_ENV" ""

download_model() {
    local python="$1" model="$2" gated="${3:-0}" pattern="${4:-}"
    if HF_HUB_OFFLINE=1 "$python" - "$model" "$pattern" <<'PY'
import sys
from huggingface_hub import snapshot_download
options = {"local_files_only": True}
if sys.argv[2]:
    options["allow_patterns"] = [sys.argv[2]]
snapshot_download(sys.argv[1], **options)
PY
    then
        return
    fi
    if [[ "$OFFLINE" == 1 ]]; then
        echo "Pesos em falta no modo offline: $model" >&2
        return 1
    fi
    if [[ "$gated" == 1 && ( -z "$HF_TOKEN" || "$HF_TOKEN" != hf_* ) ]]; then
        echo "É necessário um token Hugging Face Read para descarregar $model." >&2
        return 1
    fi
    "$python" - "$model" "$pattern" <<'PY'
import os, sys
from huggingface_hub import snapshot_download
options = {"token": os.environ.get("HF_TOKEN") or None}
if sys.argv[2]:
    options["allow_patterns"] = [sys.argv[2]]
snapshot_download(sys.argv[1], **options)
PY
}

log "Garantir pesos no cache local"
download_model "$SPAR_ENV/bin/python" stabilityai/stable-point-aware-3d 1
download_model "$SF3D_ENV/bin/python" stabilityai/stable-fast-3d 1
download_model "$SF3D_ENV/bin/python" facebook/dinov2-large 0
download_model "$SF3D_ENV/bin/python" laion/CLIP-ViT-B-32-laion2B-s34B-b79K 0 open_clip_pytorch_model.bin

alpha_clip_file="$ALPHA_CLIP_PATH/ViT-L-14-336px.pt"
if [[ ! -s "$alpha_clip_file" && -s /root/.cache/clip/ViT-L-14-336px.pt ]]; then
    cp /root/.cache/clip/ViT-L-14-336px.pt "$alpha_clip_file"
fi
if [[ ! -s "$alpha_clip_file" ]]; then
    log "Descarregar checkpoint AlphaCLIP usado pelo SPAR3D"
    "$SPAR_ENV/bin/python" - <<'PY'
import os
from alpha_clip.alpha_clip import _MODELS, _download
_download(_MODELS["ViT-L/14@336px"], os.environ["ALPHA_CLIP_PATH"])
PY
fi

log "Validar imports dos dois motores"
env PYTHONPATH="$SPAR_REPO" HF_HUB_OFFLINE=1 "$SPAR_ENV/bin/python" - <<'PY'
import torch
from flet import FilePickerResultEvent
from transparent_background import Remover
from spar3d.system import SPAR3D
import texture_baker, uv_unwrapper
assert torch.cuda.is_available()
print("SPAR3D_IMPORT_OK", torch.__version__, torch.version.cuda, torch.cuda.get_device_name(0))
PY
env PYTHONPATH="$SF3D_REPO" HF_HUB_OFFLINE=1 "$SF3D_ENV/bin/python" - <<'PY'
import torch
from sf3d.system import SF3D
import texture_baker, uv_unwrapper
assert torch.cuda.is_available()
print("SF3D_IMPORT_OK", torch.__version__, torch.version.cuda, torch.cuda.get_device_name(0))
PY

log "Criar entrada de smoke test"
"$SF3D_ENV/bin/python" - <<'PY'
from PIL import Image, ImageDraw
image = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((105, 145, 407, 390), radius=58, fill=(42, 118, 210, 255))
draw.ellipse((205, 70, 307, 172), fill=(72, 148, 235, 255))
image.save("/opt/matias-ai/smoke-input.png")
PY

validate_glb() {
    local path="$1"
    [[ -s "$path" ]] || return 1
    [[ "$(stat -c %s "$path")" -ge 10000 ]] || return 1
    [[ "$(head -c 4 "$path")" == glTF ]]
}

worker_hash="$(sha256sum "$ROOT/local_ai_worker.py" | cut -d' ' -f1)"
smoke_stamp="$ROOT/.smoke-worker.sha256"
if [[ ! -f "$smoke_stamp" || "$(<"$smoke_stamp")" != "$worker_hash" ]] || ! validate_glb "$ROOT/smoke-spar3d.glb" || ! validate_glb "$ROOT/smoke-sf3d.glb"; then
    log "Gerar GLB real com Stable Fast 3D (fallback)"
    rm -f "$ROOT/smoke-sf3d.glb"
    timeout 7200 env HF_HUB_OFFLINE=1 "$SF3D_ENV/bin/python" "$ROOT/local_ai_worker.py" \
        --engine stable_fast_3d --repo "$SF3D_REPO" --input "$ROOT/smoke-input.png" \
        --output "$ROOT/smoke-sf3d.glb" --cache "$CACHE" --seed 1234 --texture-resolution 512
    validate_glb "$ROOT/smoke-sf3d.glb"

    log "Gerar GLB real com SPAR3D Low VRAM (principal)"
    rm -f "$ROOT/smoke-spar3d.glb"
    timeout 7200 env HF_HUB_OFFLINE=1 SPAR3D_LOW_VRAM=1 "$SPAR_ENV/bin/python" "$ROOT/local_ai_worker.py" \
        --engine spar3d --repo "$SPAR_REPO" --input "$ROOT/smoke-input.png" \
        --output "$ROOT/smoke-spar3d.glb" --cache "$CACHE" --seed 1234 --texture-resolution 512 --low-vram
    validate_glb "$ROOT/smoke-spar3d.glb"
    printf '%s' "$worker_hash" > "$smoke_stamp"
fi

stat -c 'SPAR3D_GLB %s bytes %n' "$ROOT/smoke-spar3d.glb"
stat -c 'SF3D_GLB %s bytes %n' "$ROOT/smoke-sf3d.glb"
log "Instalação Linux concluída"
