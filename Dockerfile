FROM python:3.14-alpine

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /octopus_usage_exporter

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-cache --no-install-project

COPY octopus_usage_exporter /octopus_usage_exporter

RUN uv sync --frozen --no-cache

CMD ["uv", "run", "python", "octopus_usage_exporter.py"]
