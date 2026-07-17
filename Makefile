.PHONY: install dev test build docker
install:
	cd frontend && npm install
	python -m pip install -r backend/requirements.txt
dev:
	@echo "Executa em dois terminais: make backend e make frontend"
backend:
	cd backend && uvicorn app.main:app --reload --port 8000
frontend:
	cd frontend && npm run dev
test:
	cd backend && pytest -q
build:
	cd frontend && npm run build
docker:
	docker compose up --build

