from prometheus_client import MetricsHandler, Gauge
from datetime import datetime, timedelta
import logging
import os
import threading
import time
from http.server import HTTPServer
from gql import gql
from pydantic_settings import BaseSettings, SettingsConfigDict


from gas_meter import gas_meter
from electric_meter import electric_meter
from octopus_api_connection import octopus_api_connection
from utils import strip_device_id, from_iso, from_iso_timestamp
from gauge_definitions import GaugeDefinitions


logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')


version = "0.1.7"
gauges = {}

prom_port = int(os.environ.get('PROM_PORT', 9120))
account_number = os.environ.get('ACCOUNT_NUMBER')

meters = []

interval = 1800

class PrometheusEndpointServer(threading.Thread):
    def __init__(self, httpd, *args, **kwargs):
        self.httpd = httpd
        super(PrometheusEndpointServer, self).__init__(*args, **kwargs)

    def run(self):
        self.httpd.serve_forever()

class Settings(BaseSettings):
    model_config = SettingsConfigDict()
    prom_port: int = 9120
    account_number: str
    api_key: str
    gas: bool = False
    electric: bool = False
    ng_metrics: bool = False
    tariff_rates: bool = False
    tariff_remaining: bool = False
    interval: int = 1800

def start_prometheus_server():
    try:
        httpd = HTTPServer(("0.0.0.0", prom_port), MetricsHandler)
    except (OSError) as e:
        logging.error("Failed to start Prometheus server: %s", str(e))
        return

    thread = PrometheusEndpointServer(httpd)
    thread.daemon = True
    thread.start()
    logging.info("Exporting Prometheus /metrics/ on port %s", prom_port)


def get_device_id(client, gas, electric):
    gas_query = gql("""
        query Account($accountNumber: String!) {
            account(accountNumber: $accountNumber) {
                id
                gasAgreements {
                id
                ... on GasAgreementType {
                    id
                    tariff {
                        displayName
                    }
                }
                meterPoint {
                    id
                    meters {
                    id
                    smartGasMeter {
                        id
                        deviceId
                    }
                    }
                }
                }
            }
            }
    """)

    elec_query = gql("""
        query Account($accountNumber: String!) {
            account(accountNumber: $accountNumber) {
                id
                electricityAgreements {
                id
                ... on ElectricityAgreementType {
                    id
                    tariff {
                        ... on StandardTariff {
                            displayName
                        }
                        ... on DayNightTariff {
                            displayName
                        }
                        ... on ThreeRateTariff {
                            displayName
                        }
                        ... on HalfHourlyTariff {
                            displayName
                        }
                        ... on PrepayTariff {
                            displayName
                        }
                    }
                }
                meterPoint {
                    id
                    meters {
                    smartImportElectricityMeter {
                        id
                        deviceId
                    }
                    }
                }
                }
            }
            }
    """)

    if electric:
        electric_query = client.execute(elec_query, variable_values={"accountNumber": account_number})
        usable_smart_meters = [m for m in electric_query["account"]["electricityAgreements"][0]["meterPoint"]["meters"]
                               if m['smartImportElectricityMeter'] is not None]
        selected_smart_meter_device_id = usable_smart_meters[0]["smartImportElectricityMeter"]["deviceId"]
        meters.append(electric_meter(
            device_id=selected_smart_meter_device_id,
            meter_type="electric",
            polling_interval=Settings().interval,
            last_called=datetime.now() - timedelta(seconds=interval),
            reading_types=["consumption", "demand"] +
            (["tariff_expiry", "tariff_days_remaining"] if Settings().tariff_remaining else []) +
            (["tariff_unit_rate", "tariff_standing_charge"] if Settings().tariff_rates else []),
            agreement=electric_query["account"]["electricityAgreements"][0]["id"]
        ))
        logging.info("Electricity Meter has been found - {}".format(selected_smart_meter_device_id))
        logging.info("Electricity Tariff information: {}".format(electric_query["account"]["electricityAgreements"][0]["tariff"]["displayName"]))
    if gas:
        gas_query = client.execute(gas_query, variable_values={"accountNumber": account_number})
        usable_smart_meters = [m for m in gas_query["account"]["gasAgreements"][0]["meterPoint"]["meters"]
                               if m['smartGasMeter'] is not None]
        selected_smart_meter_device_id = usable_smart_meters[0]["smartGasMeter"]["deviceId"]
        meters.append(gas_meter(device_id=selected_smart_meter_device_id, meter_type="gas",
                                   polling_interval=1800,
                                   last_called=datetime.now()-timedelta(seconds=1800),
                                   reading_types=["consumption"] +
                                    (["tariff_expiry", "tariff_days_remaining"] if Settings().tariff_remaining else []) +
                                    (["tariff_unit_rate", "tariff_standing_charge"] if Settings().tariff_rates else []),
                                   agreement=gas_query["account"]["gasAgreements"][0]["id"]))
        logging.info("Gas Meter has been found - {}".format(selected_smart_meter_device_id))
        logging.info("Gas Tariff information: {}".format(gas_query["account"]["gasAgreements"][0]["tariff"]["displayName"]))


def get_energy_reading(client, meter):
    output_readings = {}
    # Dynamically build the query based on which agreement IDs are provided
    query = meter.get_jql_query()
    variables = {"deviceId": meter.device_id, "agreementId": meter.agreement}

    try:
        reading_query_ex = client.execute(query, variable_values=variables)
        returned_telemetry = reading_query_ex["smartMeterTelemetry"][0]

        if meter.meter_type == "electric":
            if reading_query_ex["electricityAgreement"]["isRevoked"]:
                logging.warning("Electricity agreement {} is revoked, no tariff information will be returned.".format(meter.agreement))
                return {}
            if reading_query_ex["electricityAgreement"]["validTo"]:
                valid_to = from_iso(reading_query_ex["electricityAgreement"]["validTo"])
                if valid_to < datetime.now(valid_to.tzinfo):
                    logging.warning("Electricity agreement {} is no longer valid, no tariff information will be returned".format(meter.agreement))
                    return {}
            for key,value in electricity_tariff_parser(reading_query_ex["electricityAgreement"]).items():
                output_readings[key] = value
        elif meter.meter_type == "gas":
            if reading_query_ex["gasAgreement"]["isRevoked"]:
                logging.warning("Gas agreement {} is revoked, no tariff information will be returned.".format(meter.agreement))
                return {}
            if reading_query_ex["gasAgreement"]["validTo"]:
                valid_to = from_iso(reading_query_ex["gasAgreement"]["validTo"])
                if valid_to < datetime.now(valid_to.tzinfo):
                    logging.warning("Gas agreement {} is no longer valid, no tariff information will be returned".format(meter.agreement))
                    return {}
                output_readings["tariff_unit_rate"] = reading_query_ex["gasAgreement"]["tariff"]["unitRate"]
                output_readings["tariff_standing_charge"] = reading_query_ex["gasAgreement"]["tariff"]["standingCharge"]
                output_readings["tariff_expiry"] = from_iso_timestamp(reading_query_ex["gasAgreement"]["validTo"])
                output_readings["tariff_days_remaining"] = (from_iso(reading_query_ex["gasAgreement"]["validTo"]) - datetime.now(from_iso(reading_query_ex["gasAgreement"]["validTo"]).tzinfo)).days
        for wanted_type in meter.reading_types:
            if output_readings.get(wanted_type) is not None:
                pass
            elif returned_telemetry.get(wanted_type) is not None:
                output_readings[wanted_type] = returned_telemetry.get(wanted_type)
            else:
                output_readings[wanted_type] = 0
            logging.debug("Meter: {} - Type: {} - Fuel: {} - Reading: {}".format(meter.device_id, wanted_type, meter.meter_type, output_readings.get(wanted_type)))
    except IndexError:
        if not reading_query_ex["smartMeterTelemetry"]:
            logging.error("Octopus API returned no consumption or demand data for {}".format(meter.device_id))

    logging.info("Meter: {} - {} metrics collected".format(meter.device_id, len(output_readings)))
    return output_readings

def electricity_tariff_parser(tariff):

    output_map = {}

    if tariff["tariff"]["isExport"]:
        logging.debug("This is an export tariff, no unit rates will be returned")
        return output_map

    now = datetime.now().astimezone()
    t = tariff["tariff"]
    if t.get("unitRates"):
        logging.debug("Octopus 'smart' tariff detected. Half hourly rates will be returned.")
        # Find the unit rate valid for now
        current_rate = None
        for rate in t["unitRates"]:
            valid_from = from_iso(rate["validFrom"])
            valid_to = from_iso(rate["validTo"])
            if valid_from <= now and now < valid_to:
                current_rate = rate["value"]
                break
        output_map["tariff_unit_rate"] = current_rate
    elif t.get("dayRate") and t.get("nightRate") and t.get("offPeakRate"):
        logging.warning("Octopus 'three rate' tariff detected. Support for this tariff is not available yet.")
        return output_map
    elif t.get("dayRate") and t.get("nightRate"):
        logging.warning("Octopus 'day night' tariff detected. Support for this tariff is not available yet.")
        return output_map
    elif t.get("unitRate"):
        logging.debug("Octopus 'standard/prepay' tariff detected. Single unit rate will be returned.")
        output_map["tariff_unit_rate"] = t["unitRate"]

    output_map["tariff_standing_charge"] = t["standingCharge"]
    if tariff.get("validTo") and tariff.get("validTo") != "null":
        now = datetime.now(from_iso(tariff.get("validTo")).tzinfo)
        output_map["tariff_expiry"] = from_iso_timestamp(tariff.get("validTo"))
        output_map["tariff_days_remaining"] = (from_iso(tariff.get("validTo")) - now).days

    return output_map

def update_gauge(key, value, meter):
    amended_key = "oe_{}_{}_{}".format(key, strip_device_id(meter.device_id), meter.meter_type)

    try:
        value = float(value)
        if key in meter.reading_types:
            if amended_key not in gauges:
                gauges[amended_key] = Gauge(amended_key, "Octopus Energy Gauge")
            gauges[amended_key].set(value)
    except (TypeError, ValueError):
            logging.warning("Value for {} is not a float: {} - labels: {}".format(key, value, meter.return_labels()))


def update_gauge_ng(key: str, value, meter):
    amended_key = "oe_meter_{}".format(key)
    try:
        value = float(value)
        if key in meter.reading_types:
            if not gauges.get(amended_key):
                gauges[amended_key] = Gauge(amended_key, GaugeDefinitions[key].value, meter.return_labels())
            gauges[amended_key].labels(**meter.return_labels()).set(value)
    except (TypeError, ValueError):
        logging.warning("Value for {} is not a float: {} - labels: {}".format(key, value, meter.return_labels()))


def read_meters(api_connection):
    while True:
        for meter in meters:
            if (meter.last_called + timedelta(seconds=meter.polling_interval) <= datetime.now()):
                meter.last_called = datetime.now()
                for r_type, value in get_energy_reading(api_connection, meter).items():
                    update_gauge_ng(r_type, value, meter) if Settings().ng_metrics else update_gauge(r_type, value, meter)

        time.sleep(interval)

def interval_rate_check():
    global interval
    if Settings().interval > 1800:
        interval = 1800
    else:
        interval = Settings().interval
        if (interval <= 180):
            logging.warning("Attention! If you proceed with an interval below 60 you will likely hit an API rate limit set by Octopus Energy.")


def exporter():
    interval_rate_check()
    api_connection = octopus_api_connection(api_key=Settings().api_key)
    get_device_id(api_connection, Settings().gas, Settings().electric)
    for meter in meters:
        logging.info("Starting to read {} meter every {} seconds".format(meter.meter_type, meter.polling_interval))
    start_prometheus_server()
    read_meters(api_connection)


if __name__ == '__main__':
    logging.info("Octopus Energy Exporter by JRP - Version {}".format(version))
    exporter()


