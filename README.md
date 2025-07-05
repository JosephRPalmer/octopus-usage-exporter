# Octopus Usage Exporter

Prometheus exporter for Octopus Energy metrics. Works best when coupled with an Octopus Home Mini.

Returns:
- Consumption (Gas and Electric)
- Demand (if you have a Smart Meter) (Electric Only)
- Tariff Information (Standard and 'Smart' Half Hourly Tariffs only, 3 rate and day/night rate not currently supported)
  - Standing Charge
  - Current Unit Rate


## Working Items
- Prometheus Exporter
## How To Use

- Make use of the docker compose example below or the example in the repo and customise for your use case
- Set the following environment vars:
      - PROM_PORT=9120 (Prometheus Port)
      - INTERVAL=300 (Scraping interval)
      - API_KEY=abc123 (Octopus Energy API key)
      - ACCOUNT_NUMBER=A-ABC12E04 (Octopus Energy Account number)
      - GAS=True (Gas stat scraping)
      - ELECTRIC=True (Electric stat scraping)
      - NG_METRICS=False (New for 0.0.24, metrics move to use a proper label format outside of metric names. Defaults to false with existing metric format, setting to True will enable new formatting. This behaviour will change in future major release.)
- Ensure the ports exposed in the docker compose match the port referenced under PROM_PORT

## Docker Compose Example

```
version: "3.3"

services:
  octopus-usage-exporter:
    image: ghcr.io/josephrpalmer/octopus-usage-exporter:latest
    container_name: octopus-usage-exporter
    network_mode: bridge
    restart: always
    environment:
      - PROM_PORT=9120
      - INTERVAL=60
      - API_KEY=abc123
      - ACCOUNT_NUMBER=A-ABC12E04
      - GAS=True
      - ELECTRIC=True
      - NG_METRICS=False
    ports:
      - "9120:9120"

```

## Grafana Dashboard Example

An example [grafana dashboard](./examples/grafana_dashboard.json) can be found in the
examples directory. This shows stats relating to current, max, min and average consumption, as well
as total consumption.

![](./examples/grafana_dashboard.png)
