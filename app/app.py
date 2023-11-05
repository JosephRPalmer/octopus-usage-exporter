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

from energy_meter import energy_meter

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
requests_logger.setLevel(logging.WARNING)

version = "0.0.6"
gauges = {}

prom_port = int(os.environ.get('PROM_PORT', 9120))

response = httpx.get(url="https://auth.octopus.energy/.well-known/jwks.json")
key = response.json()


headers = {}
transport = RequestsHTTPTransport(url="https://api.octopus.energy/v1/graphql/#", headers=headers, verify=True,retries=3)

meters = []

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
    except (OSError, socket.error) as e:
        logging.error("Failed to start Prometheus server: %s", str(e))
        return

    thread = PrometheusEndpointServer(httpd)
    thread.daemon = True
    thread.start()
    logging.info("Exporting Prometheus /metrics/ on port %s", prom_port)


def get_device_id():
    query = gql("""
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
    account_query = oe_client.execute(query, variable_values={"accountNumber": "A-23FBB1B1"})
    meters.append(energy_meter("electric_meter", account_query["account"]["electricityAgreements"][0]["meterPoint"]["meters"][0]["smartImportElectricityMeter"]["deviceId"], "electric", int(os.environ.get("INTERVAL")), datetime.now()-timedelta(seconds=interval), ["consumption", "demand"]))
    meters.append(energy_meter("gas_meter", account_query["account"]["gasAgreements"][0]["meterPoint"]["meters"][0]["smartGasMeter"]["deviceId"], "gas", 3600, datetime.now(), ["consumption"]))

    for meter in meters:  # Iterate directly over the objects in the list
        logging.info("Meter: {} - ID: {} added".format(meter.meter_type, meter.device_id))

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
        reading_query_returned = oe_client.execute(query, variable_values={"deviceId": meter_id})["smartMeterTelemetry"][0]
        for wanted_type in reading_types:
            if reading_query_returned[wanted_type] == None:
                output_readings[wanted_type] = 0
            else:
                output_readings[wanted_type] = reading_query_returned[wanted_type]
            logging.info("Meter: {} - Type: {} - Reading: {}".format(meter_id, wanted_type, reading_query_returned[wanted_type]))
    except gql.transport.exceptions.TransportQueryError:
        logging.warning("Possible rate limit hit, increase call interval")

    return output_readings
def update_gauge(key, value):
    if key not in gauges:
        gauges[key] = Gauge(key, 'Octopus Energy gauge')
    gauges[key].set(value)

def get_jwt(api_key):
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

def initial_load(api_key):
    get_jwt(api_key)
    get_device_id()

def check_jwt(api_key):
    user_info = jwt.decode(headers["Authorization"].split(" ")[1], key=key , algorithms=["RS256"])


    if (datetime.fromtimestamp(user_info["exp"]) > datetime.now() + timedelta(minutes=5)):
        logging.info("JWT valid until {}".format(datetime.fromtimestamp(user_info["exp"])))
    else:
        get_jwt(api_key)

def read_meters(api_key):
    while True:
        check_jwt(api_key)
        for meter in meters:
            if (meter.last_called + timedelta(seconds=meter.polling_interval) <= datetime.now()):
                meter.last_called = datetime.now()
                for r_type, value in get_energy_reading(meter.device_id, meter.reading_types).items():
                    update_gauge("oe_{}_{}_{}".format(r_type, strip_device_id(meter.device_id), meter.meter_type),float(value))

        time.sleep(interval)

def strip_device_id(id):
    return id.replace('-','')

def interval_rate_check():
    global interval
    if (int(os.environ.get("INTERVAL")) > 3600):
        interval = 3600
    else:
        interval = int(os.environ.get("INTERVAL"))
        if (interval <= 180):
            logging.warning("Attention! If you proceed with an interval below 60 you will likely hit an API rate limit set by Octopus Energy.")

if __name__ == '__main__':
    logging.info("Octopus Energy Exporter by JRP - Version {}".format(version))
    interval_rate_check()
    initial_load(str(os.environ.get("API_KEY")))
    for meter in meters:
        logging.info("Starting to read {} meter every {} seconds".format(meter.meter_type, meter.polling_interval))
    start_prometheus_server()
    read_meters(str(os.environ.get("API_KEY")))
