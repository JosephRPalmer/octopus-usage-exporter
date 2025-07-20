from prometheus_client import MetricsHandler, Gauge
import httpx
from datetime import datetime, timedelta
from enum import Enum
from jose import jwt
import logging
import os
import threading
import time
from http.server import HTTPServer
from gql import Client, gql
from gql.transport.requests import RequestsHTTPTransport, log as requests_logger
from gql.transport.exceptions import TransportQueryError
from pydantic_settings import BaseSettings, SettingsConfigDict


from gas_meter import gas_meter
from electric_meter import electric_meter

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
requests_logger.setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

version = "0.1.3"
gauges = {}

prom_port = int(os.environ.get('PROM_PORT', 9120))
account_number = os.environ.get('ACCOUNT_NUMBER')

response = httpx.get(url="https://auth.octopus.energy/.well-known/jwks.json")
key = response.json()


headers = {}
transport = RequestsHTTPTransport(url="https://api.octopus.energy/v1/graphql/#", headers=headers, verify=True,retries=3)

meters = []

interval = 1800

oe_client = Client(transport=transport, fetch_schema_from_transport=False)

class GaugeDefinitions(str, Enum):
    consumption= "Total consumption in kWh"
    demand= "Total demand in watts"
    tariff_unit_rate= "Unit rate of the tariff in pence per kWh"
    tariff_standing_charge= "Standing charge of the tariff in pence per day"
    tariff_expiry= "Expiry date of the tariff in epoch seconds"
    tariff_days_remaining= "Days remaining until the tariff expires"

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


def get_device_id(gas, electric):
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
        electric_query = oe_client.execute(elec_query, variable_values={"accountNumber": account_number})
        usable_smart_meters = [m for m in electric_query["account"]["electricityAgreements"][0]["meterPoint"]["meters"]
                               if m['smartImportElectricityMeter'] is not None]
        selected_smart_meter_device_id = usable_smart_meters[0]["smartImportElectricityMeter"]["deviceId"]
        meters.append(electric_meter(
            name="electric_meter",
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
        gas_query = oe_client.execute(gas_query, variable_values={"accountNumber": account_number})
        usable_smart_meters = [m for m in gas_query["account"]["gasAgreements"][0]["meterPoint"]["meters"]
                               if m['smartGasMeter'] is not None]
        selected_smart_meter_device_id = usable_smart_meters[0]["smartGasMeter"]["deviceId"]
        meters.append(gas_meter(name="gas_meter",
                                   device_id=selected_smart_meter_device_id, meter_type="gas",
                                   polling_interval=1800,
                                   last_called=datetime.now()-timedelta(seconds=1800),
                                   reading_types=["consumption"] +
                                    (["tariff_expiry", "tariff_days_remaining"] if Settings().tariff_remaining else []) +
                                    (["tariff_unit_rate", "tariff_standing_charge"] if Settings().tariff_rates else []),
                                   agreement=gas_query["account"]["gasAgreements"][0]["id"]))
        logging.info("Gas Meter has been found - {}".format(selected_smart_meter_device_id))
        logging.info("Gas Tariff information: {}".format(gas_query["account"]["gasAgreements"][0]["tariff"]["displayName"]))


def get_energy_reading(meter):
    output_readings = {}
    # Dynamically build the query based on which agreement IDs are provided
    query = meter.get_jql_query()
    variables = {"deviceId": meter.device_id, "agreementId": meter.agreement}

    try:
        reading_query_ex = oe_client.execute(query, variable_values=variables)
        returned_telemetry = reading_query_ex["smartMeterTelemetry"][0]
        if meter.meter_type == "electric":
            if reading_query_ex["electricityAgreement"]["isRevoked"]:
                logging.warning("Electricity agreement {} is revoked, no tariff information will be returned.".format(meter.agreement))
                return {}
            if reading_query_ex["electricityAgreement"]["validTo"]:
                valid_to = datetime.fromisoformat(reading_query_ex["electricityAgreement"]["validTo"])
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
                valid_to = datetime.fromisoformat(reading_query_ex["gasAgreement"]["validTo"])
                if valid_to < datetime.now(valid_to.tzinfo):
                    logging.warning("Gas agreement {} is no longer valid, no tariff information will be returned".format(meter.agreement))
                    return {}
                output_readings["tariff_unit_rate"] = reading_query_ex["gasAgreement"]["tariff"]["unitRate"]
                output_readings["tariff_standing_charge"] = reading_query_ex["gasAgreement"]["tariff"]["standingCharge"]
                output_readings["tariff_expiry"] = datetime.fromisoformat(reading_query_ex["gasAgreement"]["validTo"]).timestamp()
                output_readings["tariff_days_remaining"] = (datetime.fromisoformat(reading_query_ex["gasAgreement"]["validTo"]) - datetime.now(datetime.fromisoformat(reading_query_ex["gasAgreement"]["validTo"]).tzinfo)).days
        for wanted_type in meter.reading_types:
            if output_readings.get(wanted_type) is not None:
                pass
            elif returned_telemetry.get(wanted_type) is not None:
                output_readings[wanted_type] = returned_telemetry.get(wanted_type)
            else:
                output_readings[wanted_type] = 0
            logging.debug("Meter: {} - Type: {} - Fuel: {} - Reading: {}".format(meter.device_id, wanted_type, meter.meter_type, output_readings.get(wanted_type)))
    except TransportQueryError as e:
        logging.warning("Possible rate limit hit, increase call interval")
        logging.warning(e)
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
            valid_from = datetime.fromisoformat(rate["validFrom"])
            valid_to = datetime.fromisoformat(rate["validTo"])
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
        valid_to_dt = datetime.fromisoformat(tariff.get("validTo"))
        now = datetime.now(valid_to_dt.tzinfo)
        output_map["tariff_expiry"] = valid_to_dt.timestamp()
        output_map["tariff_days_remaining"] = (valid_to_dt - now).days

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


def get_jwt(api_key):
    logging.info("Dropping headers")
    headers.clear()
    if not bool(headers):
        logging.info("Dropped headers, refreshing JWT")
    else:
        logging.warning("Failed to drop headers, trying to refresh JWT anyway")
    query = gql("""
        mutation ObtainKrakenToken($apiKey: String!) {
            obtainKrakenToken(input: { APIKey: $apiKey}) {
                token
            }
        }
    """)
    jwt_query = oe_client.execute(query, variable_values={"apiKey": api_key})

    headers["Authorization"] = "JWT {}".format(jwt_query['obtainKrakenToken']['token'])

    logging.info("JWT refresh success")
    return "jwt_query['obtainKrakenToken']['token']"

def initial_load(api_key, gas, electric):
    get_jwt(api_key)
    get_device_id(gas, electric)

def check_jwt(api_key):

    try:
        user_info = jwt.decode(headers["Authorization"].split(" ")[1], key=key , algorithms=["RS256"])
        if (datetime.fromtimestamp(user_info["exp"]) > datetime.now() + timedelta(minutes=2)):
            logging.info("JWT valid until {}".format(datetime.fromtimestamp(user_info["exp"])))
        else:
            get_jwt(api_key)
    except (jwt.ExpiredSignatureError, jwt.JWTError) as e:
        logging.error("Hit error {} - {}, refreshing JWT".format(e.__class__.__name__, e))
        get_jwt(api_key)


def read_meters(api_key):
    while True:
        check_jwt(api_key)
        for meter in meters:
            if (meter.last_called + timedelta(seconds=meter.polling_interval) <= datetime.now()):
                meter.last_called = datetime.now()
                for r_type, value in get_energy_reading(meter).items():
                    update_gauge_ng(r_type, value, meter) if Settings().ng_metrics else update_gauge(r_type, value, meter)

        time.sleep(interval)

def strip_device_id(id):
    return id.replace('-','')

def interval_rate_check():
    global interval
    if Settings().interval > 1800:
        interval = 1800
    else:
        interval = Settings().interval
        if (interval <= 180):
            logging.warning("Attention! If you proceed with an interval below 60 you will likely hit an API rate limit set by Octopus Energy.")

if __name__ == '__main__':
    logging.info("Octopus Energy Exporter by JRP - Version {}".format(version))
    interval_rate_check()
    initial_load(Settings().api_key, Settings().gas, Settings().electric, Settings().ng_metrics,
                 Settings().tariff_rates, Settings().tariff_remaining)
    for meter in meters:
        logging.info("Starting to read {} meter every {} seconds".format(meter.meter_type, meter.polling_interval))
    start_prometheus_server()
    read_meters(Settings().account_number)

