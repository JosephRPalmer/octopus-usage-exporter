# Octopus Usage Exporter

[![Docker Image CI](https://github.com/JosephRPalmer/octopus-usage-exporter/actions/workflows/main.yml/badge.svg)](https://github.com/JosephRPalmer/octopus-usage-exporter/actions/workflows/main.yml) &nbsp;&nbsp; ![GitHub Tag](https://img.shields.io/github/v/tag/josephrpalmer/octopus-usage-exporter)  &nbsp;&nbsp;![GitHub Release Date](https://img.shields.io/github/release-date/josephrpalmer/octopus-usage-exporter) &nbsp; &nbsp; ![GitHub License](https://img.shields.io/github/license/josephrpalmer/octopus-usage-exporter)



Prometheus exporter for Octopus Energy metrics. Works best when coupled with an Octopus Home Mini.

Returns:
- Consumption (Gas and Electric)
- Demand (if you have a Smart Meter) (Electric Only)
- Tariff Information (Standard and 'Smart' Half Hourly Tariffs only, 3 rate and day/night rate not currently supported)
  - Standing Charge
  - Current Unit Rate
  - Days till tariff ends


## Working Items
- Prometheus Exporter
## How To Use

- Make use of the docker compose example below or the example in the repo and customise for your use case
- Set the following environment vars:
  - `PROM_PORT=9120` (Prometheus Port)
  - `INTERVAL=300` (Scraping interval in seconds)
  - `API_KEY=abc123` (Octopus Energy API key)
  - `ACCOUNT_NUMBER=A-ABC12E04` (Octopus Energy Account number)
  - `GAS=True` (Gas stat scraping)
  - `ELECTRIC=True` (Electric stat scraping)
  - `NG_METRICS=True` (New for 0.0.24, metrics move to use a proper label format outside of metric names. Defaults to false with existing metric format, setting to True will enable new formatting. This behaviour will change in future major release.)
  - `TARIFF_RATES=True` (Tariff pricing scraping)
  - `TARIFF_REMAINING=True` (Tariff agreement time remaining scrape and calculation)
- Ensure the ports exposed in the docker compose match the port referenced under PROM_PORT

## Example Metrics
```
# HELP oe_meter_tariff_unit_rate Unit rate of the tariff in pence per kWh
# TYPE oe_meter_tariff_unit_rate gauge
oe_meter_tariff_unit_rate{device_id="00-12-34-56-78-9A-BC-DE",meter_type="electric"} 22.995
oe_meter_tariff_unit_rate{device_id="00-12-34-56-78-9A-BC-DE",meter_type="gas"} 6.134415
# HELP oe_meter_tariff_standing_charge Standing charge of the tariff in pence per day
# TYPE oe_meter_tariff_standing_charge gauge
oe_meter_tariff_standing_charge{device_id="00-12-34-56-78-9A-BC-DE",meter_type="electric"} 49.98336
oe_meter_tariff_standing_charge{device_id="00-12-34-56-78-9A-BC-DE",meter_type="gas"} 31.381455
# HELP oe_meter_tariff_expiry Expiry date of the tariff in epoch seconds
# TYPE oe_meter_tariff_expiry gauge
oe_meter_tariff_expiry{device_id="00-12-34-56-78-9A-BC-DE",meter_type="electric"} 1.782342e+09
oe_meter_tariff_expiry{device_id="00-12-34-56-78-9A-BC-DE",meter_type="gas"} 1.7750844e+09
# HELP oe_meter_tariff_days_remaining Days remaining until the tariff expires
# TYPE oe_meter_tariff_days_remaining gauge
oe_meter_tariff_days_remaining{device_id="00-12-34-56-78-9A-BC-DE",meter_type="electric"} 349.0
oe_meter_tariff_days_remaining{device_id="00-12-34-56-78-9A-BC-DE",meter_type="gas"} 265.0
# HELP oe_meter_consumption Total consumption in kWh
# TYPE oe_meter_consumption gauge
oe_meter_consumption{device_id="00-12-34-56-78-9A-BC-DE",meter_type="electric"} 5.582643e+06
oe_meter_consumption{device_id="00-12-34-56-78-9A-BC-DE",meter_type="gas"} 1.451495518e+07
# HELP oe_meter_demand Total demand in watts
# TYPE oe_meter_demand gauge
oe_meter_demand{device_id="00-12-34-56-78-9A-BC-DE",meter_type="electric"} 439.6
```

## Docker Compose Example

```yaml
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
      - NG_METRICS=True
      - TARIFF_RATES=True
      - TARIFF_REMAINING=True
    ports:
      - "9120:9120"

```

## Grafana Dashboard Example

An example [grafana dashboard](./examples/grafana_dashboard_ng.json) can be found in the
examples directory. This shows stats relating to current, max, min and average consumption, as well
as total consumption.

If you are using the legacy metrics format (`NG_METRICS=False`) use [this dashboard](./examples/grafana_dashboard_legacy.json)
instead.

![](./examples/grafana_dashboard.png)
