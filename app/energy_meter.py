from pydantic import BaseModel
from datetime import datetime
class energy_meter(BaseModel):
    device_id: str | None = None
    meter_type: str | None = None
    polling_interval: int | None = None
    last_called: datetime | None = None
    reading_types: list[str] | None = None
    agreement: int | None = None


    def return_labels(self):
        labels = {}
        if self.device_id:
            labels['device_id'] = self.device_id
        if self.meter_type:
            labels['meter_type'] = self.meter_type
        return labels
