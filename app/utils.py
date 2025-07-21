from datetime import datetime

def strip_device_id(id):
    return id.replace('-', '')

def from_iso(date):
    return datetime.fromisoformat(date)

def from_iso_timestamp(date):
    return datetime.fromisoformat(date).timestamp()
