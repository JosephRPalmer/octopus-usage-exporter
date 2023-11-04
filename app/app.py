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

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
requests_logger.setLevel(logging.WARNING)

version = "0.0.2"
gauges = {}

prom_port = int(os.environ.get('PROM_PORT', 9120))

response = httpx.get(url="https://auth.octopus.energy/.well-known/jwks.json")
key = response.json()


headers = {}
transport = RequestsHTTPTransport(url="https://api.octopus.energy/v1/graphql/#", headers=headers, verify=True,retries=3)

meters = {}

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
    electric_device = account_query["account"]["electricityAgreements"][0]["meterPoint"]["meters"][0]["smartImportElectricityMeter"]["deviceId"]
    gas_device = account_query["account"]["gasAgreements"][0]["meterPoint"]["meters"][0]["smartGasMeter"]["deviceId"]
    logging.info("Electric Meter ID: {}".format(electric_device))
    logging.info("Gas Meter ID: {}".format(gas_device))
    meters["electric"] = electric_device
    meters["gas"] = gas_device

def get_energy_reading(meter_id, reading_type):
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

    reading_query = oe_client.execute(query, variable_values={"deviceId": meter_id})["smartMeterTelemetry"][0][reading_type]
    if (reading_query == None):
        reading_query = 0
    logging.info("Meter: {} - Type: {} - Reading: {}".format(meter_id, reading_type, reading_query))
    return reading_query
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

def read_meters(api_key, interval):
    while True:
        check_jwt(api_key)
        for i in "electric", "gas":
            update_gauge("oe_consumption_{}_{}".format(strip_device_id(meters[i]), i),float(get_energy_reading(meters[i], "consumption")))

        update_gauge("oe_demand_{}_electric".format(strip_device_id(meters["electric"])),float(get_energy_reading(meters["electric"], "demand")))

        time.sleep(interval)

def strip_device_id(id):
    return id.replace('-','')

if __name__ == '__main__':
    logging.info("Octopus Energy Exporter by JRP - Version {}".format(version))
    initial_load(str(os.environ.get("API_KEY")))
    logging.info("Starting to periodically read meters every {} seconds".format(str(os.environ.get("INTERVAL"))))
    read_meters(str(os.environ.get("API_KEY")), int(os.environ.get("INTERVAL")))


    start_prometheus_server()
