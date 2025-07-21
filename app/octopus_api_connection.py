from pydantic import BaseModel
import logging
from datetime import datetime, timedelta
from jose import jwt
import httpx
from gql import Client, gql
from gql.transport.requests import RequestsHTTPTransport, log as requests_logger
from gql.transport.exceptions import TransportQueryError

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

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
        self.key = httpx.get(url="https://auth.octopus.energy/.well-known/jwks.json").json()
        self.client = Client(
            transport=RequestsHTTPTransport(
                url=self.api_url,
                headers=self.headers,
                verify=True,
                retries=3
            ),
            fetch_schema_from_transport=False
        )
        self.get_jwt(self.api_key)

    def check_jwt(self, api_key):
        try:
            user_info = jwt.decode(self.headers["Authorization"].split(" ")[1], key=self.key , algorithms=["RS256"])
            if (datetime.fromtimestamp(user_info["exp"]) > datetime.now() + timedelta(minutes=2)):
                logging.info("JWT valid until {}".format(datetime.fromtimestamp(user_info["exp"])))
            else:
                self.get_jwt(api_key)
        except (jwt.ExpiredSignatureError, jwt.JWTError) as e:
            logging.error("Hit error {} - {}, refreshing JWT".format(e.__class__.__name__, e))
            self.get_jwt(api_key)

    def get_jwt(self, api_key):
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
        jwt_query = self.client.execute(query, variable_values={"apiKey": api_key})

        self.headers["Authorization"] = "JWT {}".format(jwt_query['obtainKrakenToken']['token'])

        logging.info("JWT refresh success")
        return "jwt_query['obtainKrakenToken']['token']"

    def get_client(self):
        self.check_jwt(self.api_key)

        return self.client
