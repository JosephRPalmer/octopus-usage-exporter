from enum import Enum

class GaugeDefinitions(str, Enum):
    consumption= "Total consumption in kWh"
    demand= "Total demand in watts"
    tariff_unit_rate= "Unit rate of the tariff in pence per kWh"
    tariff_standing_charge= "Standing charge of the tariff in pence per day"
    tariff_expiry= "Expiry date of the tariff in epoch seconds"
    tariff_days_remaining= "Days remaining until the tariff expires"
