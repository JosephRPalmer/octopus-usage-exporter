import pytest
from datetime import datetime
from octopus_usage_exporter import utils

def test_strip_device_id():
    assert utils.strip_device_id('abc-def-123') == 'abcdef123'
    assert utils.strip_device_id('no-dashes') == 'nodashes'
    assert utils.strip_device_id('plainid') == 'plainid'

def test_from_iso():
    date_str = '2024-11-19T12:34:56'
    dt = utils.from_iso(date_str)
    assert isinstance(dt, datetime)
    assert dt == datetime(2024, 11, 19, 12, 34, 56)

def test_from_iso_timestamp():
    date_str = '2024-11-19T12:34:56'
    ts = utils.from_iso_timestamp(date_str)
    expected_ts = datetime(2024, 11, 19, 12, 34, 56).timestamp()
    assert abs(ts - expected_ts) < 1e-6
