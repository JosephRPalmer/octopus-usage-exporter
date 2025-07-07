from prometheus_client import MetricsHandler, Gauge
import httpx
from datetime import datetime, timedelta
from jose import jwt
import logging
import os
import threading
import time
from http.server import HTTPServer
from gql import Client, gql
from gql.transport.requests import RequestsHTTPTransport, log as requests_logger
from gql.transport.exceptions import TransportQueryError

from energy_meter import energy_meter

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
requests_logger.setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

version = "0.1.2"
gauges = {}

prom_port = int(os.environ.get('PROM_PORT', 9120))
account_number = os.environ.get('ACCOUNT_NUMBER')

response = httpx.get(url="https://auth.octopus.energy/.well-known/jwks.json")
key = response.json()


headers = {}
transport = RequestsHTTPTransport(url="https://api.octopus.energy/v1/graphql/#", headers=headers, verify=True,retries=3)

meters = []

sysconfig = {}

interval = 1800

oe_client = Client(transport=transport, fetch_schema_from_transport=False)

class PrometheusEndpointServer(threading.Thread):
    def __init__(self, httpd, *args, **kwargs):
        self.httpd = httpd
        super(PrometheusEndpointServer, self).__init__(*args, **kwargs)

    def run(self):
        self.httpd.serve_forever()


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
        meters.append(energy_meter("electric_meter", selected_smart_meter_device_id, "electric", int(os.environ.get("INTERVAL")), datetime.now()-timedelta(seconds=interval), ["consumption", "demand"], electric_query["account"]["electricityAgreements"][0]["id"] ))
        logging.info("Electricity Meter has been found - {}".format(selected_smart_meter_device_id))
        logging.info("Electricity Tariff information: {}".format(electric_query["account"]["electricityAgreements"][0]["tariff"]["displayName"]))
    if gas:
        gas_query = oe_client.execute(gas_query, variable_values={"accountNumber": account_number})
        usable_smart_meters = [m for m in gas_query["account"]["gasAgreements"][0]["meterPoint"]["meters"]
                               if m['smartGasMeter'] is not None]
        selected_smart_meter_device_id = usable_smart_meters[0]["smartGasMeter"]["deviceId"]
        meters.append(energy_meter("gas_meter", selected_smart_meter_device_id, "gas", 1800, datetime.now()-timedelta(seconds=1800), ["consumption"], gas_query["account"]["gasAgreements"][0]["id"]))
        logging.info("Gas Meter has been found - {}".format(selected_smart_meter_device_id))
        logging.info("Gas Tariff information: {}".format(gas_query["account"]["gasAgreements"][0]["tariff"]["displayName"]))


def get_energy_reading(meter_id, reading_types, agreement_id, energy_type):
    output_readings = {}
    # Dynamically build the query based on which agreement IDs are provided
    query_blocks = []
    query_blocks.append("""
            smartMeterTelemetry(deviceId: $deviceId) {
                readAt
                consumption
                demand
                consumptionDelta
                costDelta
            }
    """)
    if energy_type == "electric":
        query_blocks.append("""
            electricityAgreement(id: $electricityAgreementId) {
                isRevoked
                validTo
                ... on ElectricityAgreementType {
                    id
                    validTo
                    agreedFrom
                    tariff {
                        ... on StandardTariff {
                            id
                            displayName
                            standingCharge
                            isExport
                            unitRate
                        }
                        ... on DayNightTariff {
                            id
                            displayName
                            fullName
                            standingCharge
                            isExport
                            dayRate
                            nightRate
                        }
                        ... on ThreeRateTariff {
                            id
                            displayName
                            standingCharge
                            isExport
                            dayRate
                            nightRate
                            offPeakRate
                        }
                        ... on HalfHourlyTariff {
                            id
                            displayName
                            standingCharge
                            isExport
                            unitRates {
                                validFrom
                                validTo
                                value
                            }
                        }
                        ... on PrepayTariff {
                            id
                            displayName
                            description
                            standingCharge
                            isExport
                            unitRate
                        }
                    }
                }
            }
        """)
    elif energy_type == "gas":
        query_blocks.append("""
            gasAgreement(id: $gasAgreementId) {
                validTo
                isRevoked
                id
                validFrom
                ... on GasAgreementType {
                    id
                    isRevoked
                    tariff {
                        id
                        displayName
                        fullName
                        standingCharge
                        isExport
                        unitRate
                    }
                }
            }
        """)

    query_str = f"""
    query TariffsandMeterReadings($deviceId: String!{', $electricityAgreementId: ID!' if energy_type == "electric" else ''}{', $gasAgreementId: ID!' if energy_type == "gas" else ''}) {{
            {"\n".join(query_blocks)}
        }}
    """


    query = gql(query_str)
    variables = {"deviceId": meter_id}
    if energy_type == "electric":
        variables["electricityAgreementId"] = agreement_id
    elif energy_type == "gas":
        variables["gasAgreementId"] = agreement_id

    try:
        reading_query_ex = oe_client.execute(query, variable_values=variables)
        reading_query_returned = reading_query_ex["smartMeterTelemetry"][0]
        if energy_type == "electric" and sysconfig["tariff_rates"] or sysconfig["tariff_remaining"]:
            if reading_query_ex["electricityAgreement"]["isRevoked"]:
                logging.warning("Electricity agreement {} is revoked, no tariff information will be returned.".format(agreement_id))
                return {}
            if reading_query_ex["electricityAgreement"]["validTo"]:
                valid_to = datetime.fromisoformat(reading_query_ex["electricityAgreement"]["validTo"])
                if valid_to < datetime.now(valid_to.tzinfo):
                    logging.warning("Electricity agreement {} is no longer valid, no tariff information will be returned".format(agreement_id))
                    return {}
            for key,value in electricity_tariff_parser(reading_query_ex["electricityAgreement"]).items():
                output_readings[key] = value
        elif energy_type == "gas" and sysconfig["tariff_rates"] or sysconfig["tariff_remaining"]:
            if reading_query_ex["gasAgreement"]["isRevoked"]:
                logging.warning("Gas agreement {} is revoked, no tariff information will be returned.".format(agreement_id))
                return {}
            if reading_query_ex["gasAgreement"]["validTo"]:
                valid_to = datetime.fromisoformat(reading_query_ex["gasAgreement"]["validTo"])
                if valid_to < datetime.now(valid_to.tzinfo):
                    logging.warning("Gas agreement {} is no longer valid, no tariff information will be returned".format(agreement_id))
                    return {}
            output_readings["tariff_unit_rate"] = reading_query_ex["gasAgreement"]["tariff"]["unitRate"]
            output_readings["tariff_standing_charge"] = reading_query_ex["gasAgreement"]["tariff"]["standingCharge"]
            output_readings["tariff_days_remaining"] = (datetime.fromisoformat(reading_query_ex["gasAgreement"]["validTo"]) - datetime.now(datetime.fromisoformat(reading_query_ex["gasAgreement"]["validTo"]).tzinfo)).days if reading_query_ex["gasAgreement"]["validTo"] else None
        for wanted_type in reading_types:
            if reading_query_returned[wanted_type] == None:
                output_readings[wanted_type] = 0
            else:
                output_readings[wanted_type] = reading_query_returned[wanted_type]
            logging.info("Meter: {} - Type: {} - Reading: {}".format(meter_id, wanted_type, reading_query_returned[wanted_type]))
    except TransportQueryError as e:
        logging.warning("Possible rate limit hit, increase call interval")
        logging.warning(e)
    except IndexError:
        if not reading_query_ex["smartMeterTelemetry"]:
            logging.error("Octopus API returned no data for {}".format(meter_id))
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
        output_map["tariff_standing_charge"] = t.get("standingCharge")
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

    output_map["tariff_days_remaining"] = (datetime.fromisoformat(tariff["validTo"]) - datetime.now(datetime.fromisoformat(tariff["validTo"]).tzinfo)).days if tariff["validTo"] else None

    return output_map


def update_gauge(key, value):
    if key not in gauges:
        gauges[key] = Gauge(key, 'Octopus Energy gauge')
    gauges[key].set(value)


def update_gauge_ng(key: str, value: int, labels_dict: dict):
    if not gauges.get(key):
        gauges[key] = Gauge(key, 'Octopus Energy gauge', labels_dict.keys() if labels_dict else {})

    if labels_dict:
        gauges[key].labels(**labels_dict).set(value)
    else:
        gauges[key].set(value)

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

def initial_load(api_key, gas, electric, ng_metrics, rates, remaining):
    get_jwt(api_key)
    get_device_id(gas, electric)
    sysconfig["ng_metrics"] = ng_metrics
    sysconfig["tariff_rates"] = rates
    sysconfig["tariff_remaining"] = remaining


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
                for r_type, value in get_energy_reading(meter.device_id, meter.reading_types, meter.agreement, meter.meter_type).items():
                    if isinstance(value, float):
                        update_gauge_ng("oe_meter_{}".format(r_type), float(value), meter.return_labels()) if sysconfig["ng_metrics"] else update_gauge("oe_{}_{}_{}".format(r_type, strip_device_id(meter.device_id), meter.meter_type), float(value))
                    else:
                        logging.warning("Value for {} is not a float: {}".format(r_type, value))

        time.sleep(interval)

def strip_device_id(id):
    return id.replace('-','')

def interval_rate_check():
    global interval
    if (int(os.environ.get("INTERVAL")) > 1800):
        interval = 1800
    else:
        interval = int(os.environ.get("INTERVAL"))
        if (interval <= 180):
            logging.warning("Attention! If you proceed with an interval below 60 you will likely hit an API rate limit set by Octopus Energy.")

if __name__ == '__main__':
    logging.info("Octopus Energy Exporter by JRP - Version {}".format(version))
    interval_rate_check()
    initial_load(
        str(os.environ.get("API_KEY")),
        os.getenv("GAS", "False").lower() in ("true", "1", "t"),
        os.getenv("ELECTRIC", "False").lower() in ("true", "1", "t"),
        os.getenv("NG_METRICS", "False").lower() in ("true", "1", "t"),
        os.getenv("TARIFF_RATES", "True").lower() in ("false", "0", "f"),
        os.getenv("TARIFF_REMAINING", "True").lower() in ("false", "0", "f"),
    )
    for meter in meters:
        logging.info("Starting to read {} meter every {} seconds".format(meter.meter_type, meter.polling_interval))
    start_prometheus_server()
    read_meters(str(os.environ.get("API_KEY")))

