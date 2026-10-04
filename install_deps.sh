#!/bin/bash
# install_deps.sh — installs all Alberto AI + CrewAI deps
# Usage: bash install_deps.sh

set -e

MIRROR="${MIRROR:-https://mirrors.aliyun.com/pypi/simple/}"

# Core
pip install pyyaml fastapi uvicorn pydantic pydantic-settings httpx requests \
  pyjwt portalocker json-repair rich appdirs tomli aiofiles aiosqlite jinja2 json5 \
  chromadb openai crewai crewai-core litellm jsonref pydantic-core typing_inspection \
  annotated-types jsonschema opentelemetry-exporter-otlp-proto-http \
  --break-system-packages -i "$MIRROR" --timeout 60 --no-deps 2>&1 | tail -5

# Verify
python3 -c "import crewai; print(f'✓ CrewAI {crewai.__version__}')"
python3 -c "import fastapi; print(f'✓ FastAPI {fastapi.__version__}')"
python3 -c "import litellm; print(f'✓ LiteLLM {litellm.__version__}')"
echo "All deps OK."