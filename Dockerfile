FROM python:3.13-alpine

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY app /app

CMD python octopus_usage_exporter.py
