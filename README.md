# Octopus Usage Exporter

Prometheus exporter for Octopus Energy metrics. Works best when coupled with an Octopus Home Mini.

## Working Items
- Prometheus Exporter
## How To Use

- Make use of the docker compose example below or the example in the repo and customise for your use case
- Set the following environment vars:
      - PROM_PORT=9120 (Prometheus Port)
      - INTERVAL=300 (Scraping interval)
      - API_KEY=abc123 (Octopus Energy API key)
      - ACCOUNT_NUMBER=A-ABC12E04 (Octopus Energy Account number)
- Ensure the ports exposed in the docker compose match the port referenced under PROM_PORT

## Docker Compose Example

```
version: "3.3"

services:
  octopus-usage-exporter:
    image: josephrpalmer/octopus-usage-exporter
    container_name: octopus-usage-exporter
    network_mode: bridge
    restart: always
    environment:
      - PROM_PORT=9120
      - INTERVAL=30
      - API_KEY=abc123
      - ACCOUNT_NUMBER=A-ABC12E04
    ports:
      - "9120:9120"

```
