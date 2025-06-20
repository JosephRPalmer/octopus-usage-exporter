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

version = "0.0.24"
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
        meters.append(energy_meter("electric_meter", selected_smart_meter_device_id, "electric", int(os.environ.get("INTERVAL")), datetime.now()-timedelta(seconds=interval), ["consumption", "demand"]))
        logging.info("Electricity Meter has been found - {}".format(selected_smart_meter_device_id))
    if gas:
        gas_query = oe_client.execute(gas_query, variable_values={"accountNumber": account_number})
        usable_smart_meters = [m for m in gas_query["account"]["gasAgreements"][0]["meterPoint"]["meters"]
                               if m['smartGasMeter'] is not None]
        selected_smart_meter_device_id = usable_smart_meters[0]["smartGasMeter"]["deviceId"]
        meters.append(energy_meter("gas_meter", selected_smart_meter_device_id, "gas", 1800, datetime.now()-timedelta(seconds=1800), ["consumption"]))
        logging.info("Gas Meter has been found - {}".format(selected_smart_meter_device_id))


def get_energy_reading(meter_id, reading_types):
    output_readings = {}
    query = gql("""
        query SmartMeterTelemetry($deviceId: String!) {
            smartMeterTelemetry(deviceId: $deviceId) {
                readAt
                consumption
                demand
                consumptionDelta
                costDelta
            }
        }
    """)
    try:
        reading_query_ex = oe_client.execute(query, variable_values={"deviceId": meter_id})
        reading_query_returned = reading_query_ex["smartMeterTelemetry"][0]

        for wanted_type in reading_types:
            if reading_query_returned[wanted_type] == None:
                output_readings[wanted_type] = 0
            else:
                output_readings[wanted_type] = reading_query_returned[wanted_type]
            logging.info("Meter: {} - Type: {} - Reading: {}".format(meter_id, wanted_type, reading_query_returned[wanted_type]))
    except TransportQueryError:
        logging.warning("Possible rate limit hit, increase call interval")
    except IndexError:
        if not reading_query_ex["smartMeterTelemetry"]:
            logging.error("Octopus API returned no data for {}".format(meter_id))
    return output_readings

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

def initial_load(api_key, gas, electric, ng_metrics):
    get_jwt(api_key)
    get_device_id(gas, electric)
    sysconfig["ng_metrics"] = ng_metrics

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
                for r_type, value in get_energy_reading(meter.device_id, meter.reading_types).items():
                    update_gauge_ng("oe_meter_{}".format(r_type), float(value), meter.return_labels()) if sysconfig["ng_metrics"] else update_gauge("oe_{}_{}_{}".format(r_type, strip_device_id(meter.device_id), meter.meter_type),float(value))

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
    initial_load(str(os.environ.get("API_KEY")), os.getenv("GAS", 'False').lower() in ('true', '1', 't'),  os.getenv("ELECTRIC", 'False').lower() in ('true', '1', 't'), os.getenv("NG_METRICS", 'False').lower() in ('true', '1', 't'))
    for meter in meters:
        logging.info("Starting to read {} meter every {} seconds".format(meter.meter_type, meter.polling_interval))
    start_prometheus_server()
    read_meters(str(os.environ.get("API_KEY")))

