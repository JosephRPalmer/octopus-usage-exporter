FROM python:3.14-alpine

WORKDIR /octopus_usage_exporter

COPY pyproject.toml .

RUN pip install --no-cache-dir .

COPY octopus_usage_exporter /octopus_usage_exporter

CMD python octopus_usage_exporter.py
