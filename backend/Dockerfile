# One image, three jobs: the API, the Celery worker, and the database migration
# all run from it (see deploy/docker-compose.yml).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/opt/models

WORKDIR /app

# Install the CPU-only PyTorch build first. The default Linux wheel bundles CUDA
# libraries and adds several gigabytes the server can never use.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.4.1

COPY requirements.txt constraints.txt ./
RUN pip install -r requirements.txt -c constraints.txt

# Bake both models into the image so startup never waits on a download.
RUN python -c "from sentence_transformers import SentenceTransformer, CrossEncoder; \
SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2', device='cpu'); \
CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2', device='cpu')"

COPY . .

# The API and worker share /data and write files with mode 0600, so both must run
# as this same user.
RUN useradd --uid 10001 --create-home app \
    && mkdir -p /data/documents \
    && chown -R app:app /data /opt/models
USER app

# Models are already in the image. If you change FINDOC_RERANK_MODEL, change it in
# the download step above too. The thread/arena settings keep memory use low.
ENV HF_HUB_OFFLINE=1 \
    TOKENIZERS_PARALLELISM=false \
    OMP_NUM_THREADS=2 \
    MALLOC_ARENA_MAX=2

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
