from pydantic import BaseModel
import logging
from datetime import datetime, timedelta
from jose import jwt
from gql import Client, gql
from gql.transport.requests import RequestsHTTPTransport, log as requests_logger
from gql.transport.exceptions import TransportQueryError
from urllib3.exceptions import ResponseError
import requests
import backoff

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger('backoff').addHandler(logging.StreamHandler())
logging.getLogger("requests.packages.urllib3").setLevel(logging.WARNING)
logging.getLogger('backoff').setLevel(logging.WARNING)
requests_logger.setLevel(logging.WARNING)

class octopus_api_connection(BaseModel):
    model_config = {
        "arbitrary_types_allowed": True,
    }
    api_key: str
    api_url: str = "https://api.octopus.energy/v1/graphql/"
    headers: dict = {}
    key: dict = {}
    client: Client = None

    def __init__(self, **data):
        super().__init__(**data)
        self.key = requests.get(url="https://auth.octopus.energy/.well-known/jwks.json").json()
        self.client = Client(
            transport=RequestsHTTPTransport(
                url=self.api_url,
                headers=self.headers,
                verify=True,
                retries=2,
                timeout=20),
            fetch_schema_from_transport=False
        )
        self.get_jwt()

    def check_jwt(self):
        if self.headers.get("Authorization") is None:
            logging.info("No JWT found, fetching new one")
            self.get_jwt()
            return
        try:
            user_info = jwt.decode(self.headers["Authorization"].split(" ")[1], key=self.key , algorithms=["RS256"])
            if (datetime.fromtimestamp(user_info["exp"]) > datetime.now() + timedelta(minutes=2)):
                logging.debug("JWT valid until {}".format(datetime.fromtimestamp(user_info["exp"])))
            else:
                self.get_jwt()
        except (jwt.ExpiredSignatureError, jwt.JWTError) as e:
            logging.error("Hit error {} - {}, refreshing JWT".format(e.__class__.__name__, e))
            self.get_jwt()

    def get_jwt(self):
        logging.info("Dropping headers")
        self.headers.clear()
        if not bool(self.headers):
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
        jwt_query = self.run_query(query, variable_values={"apiKey": self.api_key})

        self.headers["Authorization"] = "JWT {}".format(jwt_query['obtainKrakenToken']['token'])

        logging.info("JWT refresh success")
        return "jwt_query['obtainKrakenToken']['token']"

    def get_client(self):
        self.check_jwt()

        return self.client

    def execute(self, query, variable_values=None):
        self.check_jwt()
        return self.run_query(query, variable_values)

    @backoff.on_exception(backoff.expo,(TransportQueryError, ResponseError, requests.exceptions.ConnectionError), max_tries=5, jitter=backoff.full_jitter)
    def run_query(self, query, variable_values=None):
        try:
            return self.client.execute(query, variable_values=variable_values)
        except TransportQueryError as e:
            logging.error("Possible rate limit hit, increase call interval")
            logging.error(e)
            raise  # Raise to trigger retry
        except ResponseError as e:
            logging.error("Response error: {}".format(e))
            raise  # Raise to trigger retry
        except Exception as e:
            logging.error("Error executing query: {}".format(e))
            raise  # Raise to trigger retry
