import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
from octopus_usage_exporter.octopus_api_connection import octopus_api_connection

class DummyJWT:
    @staticmethod
    def decode(token, key, algorithms):
        # Simulate a JWT with exp in 15 minutes
        return {"exp": (datetime.now() + timedelta(minutes=15)).timestamp()}

@pytest.fixture
def api_conn():
    # Patch requests.get and Client.execute to avoid real HTTP/network calls
    with patch('octopus_usage_exporter.octopus_api_connection.requests.get') as mock_get, \
         patch('octopus_usage_exporter.octopus_api_connection.Client') as mock_client:
        mock_get.return_value.json.return_value = {"keys": ["dummykey"]}
        mock_instance = MagicMock()
        mock_instance.execute.return_value = {'obtainKrakenToken': {'token': 'faketoken'}}
        mock_client.return_value = mock_instance
        conn = octopus_api_connection(api_key="dummy_api_key")
        yield conn

def test_check_jwt_valid(api_conn):
    with patch('octopus_usage_exporter.octopus_api_connection.jwt', DummyJWT):
        api_conn.headers["Authorization"] = "JWT faketoken"
        with patch.object(octopus_api_connection, 'get_jwt') as mock_get_jwt:
            api_conn.check_jwt()
            mock_get_jwt.assert_not_called()

def test_check_jwt_expired(api_conn):
    class ExpiredJWT:
        @staticmethod
        def decode(token, key, algorithms):
            # Simulate a JWT with exp in the past
            return {"exp": (datetime.now() - timedelta(minutes=5)).timestamp()}
    with patch('octopus_usage_exporter.octopus_api_connection.jwt', ExpiredJWT):
        api_conn.headers["Authorization"] = "JWT faketoken"
        with patch.object(octopus_api_connection, 'get_jwt') as mock_get_jwt:
            api_conn.check_jwt()
            mock_get_jwt.assert_called_once()
