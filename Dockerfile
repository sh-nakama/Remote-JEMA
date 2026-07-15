# Multi-stage build shared by two different build contexts:
#   base  — uses only files that exist in THIS repo. Local `docker compose`
#           builds this target and runs dashboard/app.py (bind-mounted).
#   space — final stage, built by the HF Docker Space. Its build context is
#           assembled by .github/workflows/sync-space.yml, which places
#           space/app.py at the context root — so `COPY app.py` only resolves
#           there. Local builds must use `--target base` (docker-compose.yml does).
FROM python:3.11-slim AS base

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 repower

# Third-party deps first, so src/ edits don't re-download every dependency
COPY pyproject.toml .
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > requirements.txt \
    && pip install --no-cache-dir -r requirements.txt \
    && rm requirements.txt

# Editable install needs src/ present (src layout); deps already satisfied above
COPY src/ src/
RUN pip install --no-cache-dir --no-deps -e .

# data/ is written at runtime (HF Dataset pull), so the app user must own /app
RUN mkdir -p data && chown -R repower:repower /app
USER repower
ENV HOME=/home/repower

# ── HF Space image (context: the sync-space.yml deploy dir, NOT this repo) ──
FROM base AS space

COPY app.py app.py

# HF Docker Spaces require port 7860
EXPOSE 7860
CMD ["streamlit", "run", "app.py", "--server.port=7860", "--server.address=0.0.0.0"]
