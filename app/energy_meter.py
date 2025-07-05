class energy_meter:
    def __init__(self, name, device_id, meter_type, polling_interval, last_called, reading_types, agreement):
        self.name = name
        self.device_id = device_id
        self.meter_type = meter_type
        self.polling_interval = polling_interval
        self.last_called = last_called
        self.reading_types = reading_types
        self.agreement = agreement

    def return_labels(self):
        labels = {}
        if self.device_id:
            labels['device_id'] = self.device_id
        if self.meter_type:
            labels['meter_type'] = self.meter_type
        return labels
