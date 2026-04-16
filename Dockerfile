FROM python:3.12-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

# Install dependencies first for layer caching
COPY pyproject.toml ./
RUN uv pip install --system --no-cache -e ".[dev]" 2>/dev/null || true

# Copy source
COPY alexandria/ alexandria/
COPY tests/ tests/
COPY scripts/ scripts/
COPY README.md LICENSE ./

# Install the package
RUN uv pip install --system --no-cache -e .

# Verify install
RUN alexandria --version || alxia --version

# Runtime
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=base /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=base /usr/local/bin/alexandria /usr/local/bin/alexandria
COPY --from=base /usr/local/bin/alxia /usr/local/bin/alxia
COPY --from=base /app/alexandria /app/alexandria

WORKDIR /data
ENV ALEXANDRIA_HOME=/data

ENTRYPOINT ["alxia"]
CMD ["--help"]
