# Alberto AI v1.8 - Dockerfile
# Closes G-O2: Sem Dockerfile oficial
#
# Build:  docker build -t alberto-ai:v1.8 .
# Run:    docker run -it --rm -e NVIDIA_API_KEY=$NVIDIA_API_KEY alberto-ai:v1.8
#
# Note: This is the LITE version that runs Alberto on host with
# LocalSandbox. For full NemoClaw isolation, see Dockerfile.nemoclaw.

FROM python:3.11-slim

LABEL maintainer="Alberto AI"
LABEL description="Alberto AI v1.8 - integrated AI agent stack"
LABEL version="1.8"

WORKDIR /app

# Install system deps (curl for health checks, git for skills)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY alberto ./alberto
COPY bin ./bin
COPY personas ./personas
COPY workflows ./workflows
COPY skills ./skills
COPY frontend ./frontend
COPY setup.py pyproject.toml ./

# Install in editable mode
RUN pip install -e .

# Make CLI binaries executable
RUN chmod +x bin/alberto-serve

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8741/api/status || exit 1

# Default: show banner
CMD ["alberto", "banner"]

# Expose HTTP server port
EXPOSE 8741
