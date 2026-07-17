"""Run one project synchronously for local diagnostics and recovery."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.database import SessionLocal  # noqa: E402
from app.models import Project, ReconstructionJob, ReconstructionStage  # noqa: E402
from app.reconstruction import STAGES, run_job  # noqa: E402
from app.validation import validate_project  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("project_id")
    args = parser.parse_args()
    db = SessionLocal()
    project = db.get(Project, args.project_id)
    if not project:
        raise SystemExit("Projeto não encontrado.")
    report = validate_project(db, project)
    print(f"Validação: {report['score']}/100; {report['approved']} aprovadas; {report['warnings']} avisos")
    job = ReconstructionJob(project_id=project.id, configuration={"mode": "colmap", "manual_run": True})
    db.add(job)
    db.flush()
    for order, name in enumerate(STAGES, 1):
        db.add(ReconstructionStage(job_id=job.id, name=name, order=order))
    project.status = "queued"
    db.commit()
    job_id = job.id
    db.close()
    print(f"Job: {job_id}")
    run_job(job_id)
    db = SessionLocal()
    finished = db.get(ReconstructionJob, job_id)
    print(f"Estado: {finished.status}; progresso: {finished.progress}%")
    if finished.error_message:
        print(f"Erro: {finished.error_message}")
    print(f"Métricas: {finished.metrics}")
    db.close()
    raise SystemExit(0 if finished.status == "completed" else 1)


if __name__ == "__main__":
    main()
