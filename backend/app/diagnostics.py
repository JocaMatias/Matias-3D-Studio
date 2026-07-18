import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import psutil
from sqlalchemy import text

from .config import settings
from .database import engine
from .reconstruction import reconstruction_engine_status


def _check(name: str, ok: bool, detail: str, level: str = "required") -> dict:
    return {"name": name, "ok": bool(ok), "detail": detail, "level": level}


def system_diagnostics() -> dict:
    checks: list[dict] = []
    checks.append(_check("Python", sys.version_info >= (3, 11), f"{platform.python_version()} · {platform.system()} {platform.release()}"))
    memory_gb = psutil.virtual_memory().total / 1024 ** 3
    checks.append(_check("Memória", memory_gb >= 8, f"{memory_gb:.1f} GB RAM", "recommended"))
    disk = shutil.disk_usage(settings.storage_root.parent if settings.storage_root.parent.exists() else Path.cwd())
    free_gb = disk.free / 1024 ** 3
    checks.append(_check("Espaço livre", free_gb >= 10, f"{free_gb:.1f} GB disponíveis", "recommended"))

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks.append(_check("Base de dados", True, "Ligação operacional"))
    except Exception as exc:
        checks.append(_check("Base de dados", False, f"Falhou: {exc}"))

    try:
        settings.storage_root.mkdir(parents=True, exist_ok=True)
        marker = settings.storage_root / ".write-test"
        marker.write_text("ok", encoding="utf-8")
        marker.unlink()
        checks.append(_check("Armazenamento", True, "Leitura e escrita operacionais"))
    except Exception as exc:
        checks.append(_check("Armazenamento", False, f"Falhou: {exc}"))

    engine_status = reconstruction_engine_status()
    checks.append(_check("Motor 3D", bool(engine_status.get("available")), engine_status.get("message", "Sem informação")))

    gpu = {"available": False, "name": None, "memory_mb": None}
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        try:
            result = subprocess.run(
                [nvidia_smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            ).stdout.strip().splitlines()[0]
            name, memory = [part.strip() for part in result.split(",", 1)]
            gpu = {"available": True, "name": name, "memory_mb": int(memory)}
        except Exception:
            pass
    checks.append(_check("GPU NVIDIA", gpu["available"], f"{gpu['name']} · {gpu['memory_mb']} MB" if gpu["available"] else "Não detetada; será usado CPU quando suportado", "recommended"))
    texture_ready = bool(gpu["available"] and gpu["memory_mb"] and gpu["memory_mb"] >= 15000)
    texture_detail = "VRAM suficiente para Hunyuan Paint" if texture_ready else "Será tentado offload para RAM; se não couber, mantém-se o material PBR base"
    checks.append(_check("Textura IA", texture_ready, texture_detail, "recommended"))

    queue = {"mode": settings.queue_mode, "available": True, "detail": "Fila local em memória"}
    if settings.queue_mode.lower() == "rq":
        try:
            from redis import Redis
            Redis.from_url(settings.redis_url).ping()
            queue["detail"] = "Redis/RQ operacional"
        except Exception as exc:
            queue = {"mode": settings.queue_mode, "available": False, "detail": f"Redis indisponível: {exc}"}
    checks.append(_check("Fila de trabalho", queue["available"], queue["detail"]))

    required_ok = all(check["ok"] for check in checks if check["level"] == "required")
    return {"status": "ready" if required_ok else "attention", "checks": checks, "gpu": gpu, "queue": queue, "engine": engine_status}


def main() -> None:
    print(json.dumps(system_diagnostics(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
