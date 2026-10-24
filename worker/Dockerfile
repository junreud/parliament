FROM python:3.12.11-slim AS build
RUN pip install --no-cache-dir uv==0.10.4
WORKDIR /app/worker
COPY pyproject.toml uv.lock ./
COPY src ./src
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON_DOWNLOADS=never
RUN uv sync --locked --no-dev --no-editable --extra aws

FROM python:3.12.11-slim
RUN groupadd --system --gid 10001 parliament && useradd --system --uid 10001 --gid parliament --home-dir /data parliament && mkdir -p /data && chown parliament:parliament /data
COPY --from=build /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /data
USER 10001:10001
ENTRYPOINT ["parliament-worker"]
CMD ["--help"]
