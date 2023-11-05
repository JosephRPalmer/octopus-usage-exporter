class energy_meter:
    def __init__(self, name, device_id, meter_type, polling_interval, last_called, reading_types):
        self.name = name
        self.device_id = device_id
        self.meter_type = meter_type
        self.polling_interval = polling_interval
        self.last_called = last_called
        self.reading_types = reading_types
