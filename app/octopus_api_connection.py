from pydantic import BaseModel
import logging
import jwt
import httpx
from gql import Client, gql
from gql.transport.requests import RequestsHTTPTransport, log as requests_logger
from gql.transport.exceptions import TransportQueryError

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

class octopus_api_connection(BaseModel):
    api_key: str
    api_url: str = "https://api.octopus.energy/v1/"
    headers: dict = {}
    key: dict = httpx.get(url="https://auth.octopus.energy/.well-known/jwks.json").json()
    client: Client = Client(transport=RequestsHTTPTransport(url="https://api.octopus.energy/v1/graphql/#", headers=headers, verify=True,retries=3), fetch_schema_from_transport=False)


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
        jwt_query = oe_client.execute(query, variable_values={"apiKey": api_key})

        self.headers["Authorization"] = "JWT {}".format(jwt_query['obtainKrakenToken']['token'])

        logging.info("JWT refresh success")
        return "jwt_query['obtainKrakenToken']['token']"
