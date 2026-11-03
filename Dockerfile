# MasterBA image (spec 11 section 5.1). Build: docker compose build
# The project stays at /app as an editable install, because the code finds its prompts, skills,
# templates and web app relative to the source tree.

FROM python:3.11-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.9.28 /uv /bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
WORKDIR /app
ARG EXTRAS=""
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project ${EXTRAS:+--extra "$EXTRAS"}
COPY . .
RUN uv sync --frozen --no-dev ${EXTRAS:+--extra "$EXTRAS"}

FROM python:3.11-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
ARG UID=1000
ARG GID=1000
# A host GID may already exist in the base image (macOS staff is 20, Debian dialout);
# reuse that group instead of failing.
RUN (getent group "$GID" >/dev/null || groupadd -g "$GID" masterba) \
    && useradd -u "$UID" -g "$GID" -m masterba \
    && mkdir /work /models && chown masterba:"$GID" /work /models \
    && git config --system safe.directory /work
COPY --from=builder /app /app
# HF_HOME is the model-cache volume; `kb setup` downloads the embedding model there (spec 12).
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 HF_HOME=/models MASTERBA_IN_CONTAINER=1
USER masterba
WORKDIR /work
ENTRYPOINT ["masterba", "--root", "/work"]
CMD ["doctor"]
