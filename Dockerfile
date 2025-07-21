FROM python:3.13-alpine

WORKDIR /app

COPY pyproject.toml .

RUN pip install --no-cache-dir .

COPY app /app

CMD python octopus_usage_exporter.py
