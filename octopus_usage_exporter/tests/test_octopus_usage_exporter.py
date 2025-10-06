import unittest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace
from datetime import datetime, timedelta

# Import the module under test
from octopus_usage_exporter import octopus_usage_exporter as exporter_module


class DummySettings:
    def __init__(self, interval=1800, tariff_remaining=False, tariff_rates=False, ng_metrics=False, electric=False, gas=False):
        self.interval = interval
        self.tariff_remaining = tariff_remaining
        self.tariff_rates = tariff_rates
        self.ng_metrics = ng_metrics
        self.prom_port = 9120
        self.account_number = 'ACC123'
        self.api_key = 'API'
        self.gas = electric
        self.electric = gas


class DummyMeter:
    def __init__(self, device_id='dev123', meter_type='electric', reading_types=None):
        self.device_id = device_id
        self.meter_type = meter_type
        self.reading_types = reading_types or []
        self.polling_interval = 10
        self.last_called = datetime.now() - timedelta(seconds=20)
        self.agreement = 'agreement123'

    def get_jql_query(self):
        return 'QUERY'

    def return_labels(self):
        return {"device_id": self.device_id, "fuel": self.meter_type}


class GaugeStub:
    def __init__(self, name, desc, labelnames=None):
        self.name = name
        self.desc = desc
        self.labelnames = labelnames or []
        self._value = None
        self._labels = None

    def set(self, value):
        self._value = value

    def labels(self, **labels):
        self._labels = labels
        return self


class TestElectricityTariffParser(unittest.TestCase):
    def test_export_tariff_returns_empty(self):
        tariff = {"tariff": {"isExport": True}}
        self.assertEqual(exporter_module.electricity_tariff_parser(tariff), {})

    def test_unit_rates_picks_current_rate(self):
        now = datetime.now().astimezone()
        tariff = {
            "tariff": {
                "isExport": False,
                "unitRates": [
                    {"validFrom": (now - timedelta(minutes=30)).isoformat(), "validTo": (now + timedelta(minutes=30)).isoformat(), "value": 0.301},
                ],
                "standingCharge": 0.25,
            },
            "validTo": (now + timedelta(days=2)).isoformat(),
        }
        out = exporter_module.electricity_tariff_parser(tariff)
        self.assertIn("tariff_unit_rate", out)
        self.assertAlmostEqual(out["tariff_unit_rate"], 0.301)
        self.assertEqual(out["tariff_standing_charge"], 0.25)
        self.assertIn("tariff_days_remaining", out)

    def test_standard_unit_rate(self):
        now = datetime.now().astimezone()
        tariff = {
            "tariff": {
                "isExport": False,
                "unitRate": 0.199,
                "standingCharge": 0.22,
            },
            "validTo": (now + timedelta(days=1)).isoformat(),
        }
        out = exporter_module.electricity_tariff_parser(tariff)
        self.assertEqual(out["tariff_unit_rate"], 0.199)
        self.assertEqual(out["tariff_standing_charge"], 0.22)


class TestUpdateGauge(unittest.TestCase):
    def setUp(self):
        exporter_module.gauges.clear()

    @patch.object(exporter_module, 'Gauge', GaugeStub)
    def test_update_gauge_creates_and_sets(self):
        m = DummyMeter(reading_types=['consumption'])
        exporter_module.update_gauge('consumption', 10.5, m)
        self.assertTrue(any(k.startswith('oe_consumption_') for k in exporter_module.gauges))
        g = list(exporter_module.gauges.values())[0]
        self.assertEqual(g._value, 10.5)

    @patch.object(exporter_module, 'Gauge', GaugeStub)
    @patch('octopus_usage_exporter.octopus_usage_exporter.logging.warning')
    def test_update_gauge_non_float(self, mock_warning):
        m = DummyMeter(reading_types=['consumption'])
        exporter_module.update_gauge('consumption', 'NOTFLOAT', m)
        mock_warning.assert_called_once()

    @patch.object(exporter_module, 'Gauge', GaugeStub)
    def test_update_gauge_ng_creates_and_sets(self):
        m = DummyMeter(reading_types=['consumption'])
        exporter_module.update_gauge_ng('consumption', 5.4, m)
        g = exporter_module.gauges['oe_meter_consumption']
        self.assertEqual(g._value, 5.4)
        self.assertEqual(g._labels, m.return_labels())


class TestIntervalRateCheck(unittest.TestCase):
    def test_interval_clamped(self):
        with patch('octopus_usage_exporter.octopus_usage_exporter.Settings', side_effect=lambda: DummySettings(interval=5000)):
            exporter_module.interval = 100
            exporter_module.interval_rate_check()
            self.assertEqual(exporter_module.interval, 1800)

    def test_interval_set_and_warning(self):
        with patch('octopus_usage_exporter.octopus_usage_exporter.Settings', side_effect=lambda: DummySettings(interval=120)):
            exporter_module.interval = 1000
            exporter_module.interval_rate_check()
            self.assertEqual(exporter_module.interval, 120)


class TestGetEnergyReading(unittest.TestCase):
    def test_electric_success(self):
        now = datetime.now().astimezone()
        future = (now + timedelta(hours=2)).isoformat()
        client = MagicMock()
        client.execute.return_value = {
            'smartMeterTelemetry': [{
                'consumption': 12.3,
                'demand': 1.1
            }],
            'electricityAgreement': {
                'isRevoked': False,
                'validTo': future,
                'tariff': {
                    'isExport': False,
                    'unitRates': [{
                        'validFrom': (now - timedelta(minutes=10)).isoformat(),
                        'validTo': (now + timedelta(minutes=10)).isoformat(),
                        'value': 0.25
                    }],
                    'standingCharge': 0.18
                }
            }
        }
        m = DummyMeter(reading_types=['consumption', 'demand', 'tariff_unit_rate', 'tariff_standing_charge'])
        out = exporter_module.get_energy_reading(client, m)
        self.assertEqual(out['consumption'], 12.3)
        self.assertEqual(out['demand'], 1.1)
        self.assertIn('tariff_unit_rate', out)
        self.assertIn('tariff_standing_charge', out)

    def test_electric_revoked(self):
        client = MagicMock()
        client.execute.return_value = {
            'smartMeterTelemetry': [{}],
            'electricityAgreement': {
                'isRevoked': True,
                'validTo': None,
                'tariff': { 'isExport': False }
            }
        }
        m = DummyMeter(reading_types=['consumption'])
        out = exporter_module.get_energy_reading(client, m)
        self.assertEqual(out, {})

    def test_gas_success(self):
        now = datetime.now().astimezone()
        future = (now + timedelta(days=1)).isoformat()
        client = MagicMock()
        client.execute.return_value = {
            'smartMeterTelemetry': [{
                'consumption': 5.6
            }],
            'gasAgreement': {
                'isRevoked': False,
                'validTo': future,
                'tariff': {
                    'unitRate': 0.11,
                    'standingCharge': 0.15
                }
            }
        }
        m = DummyMeter(meter_type='gas', reading_types=['consumption', 'tariff_unit_rate', 'tariff_standing_charge', 'tariff_expiry', 'tariff_days_remaining'])
        out = exporter_module.get_energy_reading(client, m)
        self.assertEqual(out['consumption'], 5.6)
        self.assertEqual(out['tariff_unit_rate'], 0.11)
        self.assertIn('tariff_expiry', out)
        self.assertIn('tariff_days_remaining', out)


class TestGetDeviceId(unittest.TestCase):
    def setUp(self):
        exporter_module.meters.clear()
        exporter_module.account_number = 'ACC123'

    def test_electric_only(self):
        fake_response = {
            'account': {
                'electricityAgreements': [{
                    'id': '12345678910',
                    'meterPoint': {
                        'meters': [
                            {'smartImportElectricityMeter': {'id': '12367829', 'deviceId': '00-AA-11-2C-3B-4D-5E-99'}},
                            {'smartImportElectricityMeter': None}
                        ]
                    },
                    'tariff': { 'displayName': 'ElecTariff' }
                }]
            }
        }
        client = MagicMock()
        client.execute.return_value = fake_response
        with patch('octopus_usage_exporter.octopus_usage_exporter.Settings', side_effect=lambda: DummySettings(interval=900)):
            exporter_module.get_device_id(client, gas=False, electric=True)
        self.assertEqual(len(exporter_module.meters), 1)
        m = exporter_module.meters[0]
        self.assertEqual(m.meter_type, 'electric')
        self.assertIn('consumption', m.reading_types)
        self.assertIn('demand', m.reading_types)

    def test_gas_only(self):
        fake_response = {
            'account': {
                'gasAgreements': [{
                    'id': '475839201',
                    'meterPoint': {
                        'meters': [
                            {'smartGasMeter': {'id': '12367829', 'deviceId': '00-AA-11-2C-3B-4D-5E-99'}},
                            {'smartGasMeter': None}
                        ]
                    },
                    'tariff': { 'displayName': 'GasTariff' }
                }]
            }
        }
        client = MagicMock()
        client.execute.return_value = fake_response
        with patch('octopus_usage_exporter.octopus_usage_exporter.Settings', side_effect=lambda: DummySettings(interval=800)):
            exporter_module.get_device_id(client, gas=True, electric=False)
        self.assertEqual(len(exporter_module.meters), 1)
        m = exporter_module.meters[0]
        self.assertEqual(m.meter_type, 'gas')
        self.assertIn('consumption', m.reading_types)


class TestStartPrometheusServer(unittest.TestCase):
    def test_start_success(self):
        class FakeHTTP:
            def __init__(self, *a, **kw):
                self.called = True
            def server_close(self):
                pass
        started = {}
        class FakeThread:
            def __init__(self, httpd):
                started['created'] = True
            def daemon(self, *a, **kw):
                pass
            def start(self):
                started['started'] = True
        with patch('octopus_usage_exporter.octopus_usage_exporter.HTTPServer', return_value=FakeHTTP()), \
             patch('octopus_usage_exporter.octopus_usage_exporter.PrometheusEndpointServer', FakeThread):
            exporter_module.start_prometheus_server()
        self.assertTrue(started.get('created'))
        self.assertTrue(started.get('started'))

    def test_start_failure(self):
        with patch('octopus_usage_exporter.octopus_usage_exporter.HTTPServer', side_effect=OSError('fail')):
            self.assertIsNone(exporter_module.start_prometheus_server())


class TestReadMeters(unittest.TestCase):
    @patch.object(exporter_module, 'update_gauge_ng')
    @patch.object(exporter_module, 'update_gauge')
    def test_read_meters_single_iteration(self, mock_simple_update, mock_ng_update):
        # Prepare
        m = DummyMeter(reading_types=['consumption'])
        exporter_module.meters = [m]
        client = MagicMock()
        with patch('octopus_usage_exporter.octopus_usage_exporter.get_energy_reading', return_value={'consumption': 3.3}), \
             patch('octopus_usage_exporter.octopus_usage_exporter.Settings', side_effect=lambda: DummySettings(ng_metrics=False)), \
             patch('octopus_usage_exporter.octopus_usage_exporter.time.sleep', side_effect=KeyboardInterrupt):
            try:
                exporter_module.read_meters(client)
            except KeyboardInterrupt:
                pass
        mock_simple_update.assert_called_with('consumption', 3.3, m)


class TestExporter(unittest.TestCase):
    def test_exporter_orchestration(self):
        with patch('octopus_usage_exporter.octopus_usage_exporter.interval_rate_check') as irc, \
             patch('octopus_usage_exporter.octopus_usage_exporter.octopus_api_connection', return_value=MagicMock()) as conn, \
             patch('octopus_usage_exporter.octopus_usage_exporter.get_device_id') as gdid, \
             patch('octopus_usage_exporter.octopus_usage_exporter.start_prometheus_server') as sps, \
             patch('octopus_usage_exporter.octopus_usage_exporter.read_meters', side_effect=KeyboardInterrupt) as rm, \
             patch('octopus_usage_exporter.octopus_usage_exporter.Settings', side_effect=lambda: DummySettings(electric=True)):
            try:
                exporter_module.exporter()
            except KeyboardInterrupt:
                pass
        irc.assert_called()
        conn.assert_called()
        gdid.assert_called()
        sps.assert_called()
        rm.assert_called()


if __name__ == '__main__':
    unittest.main()
