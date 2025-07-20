from gql import gql
from energy_meter import energy_meter

class electric_meter(energy_meter):
    def get_jql_query(self):
        query =  gql("""
        query TariffsandMeterReadings($deviceId: String!, $agreementId: ID!) {
            smartMeterTelemetry(deviceId: $deviceId) {
                readAt
                consumption
                demand
                consumptionDelta
                costDelta
            }
            electricityAgreement(id: $agreementId) {
                isRevoked
                validTo
                ... on ElectricityAgreementType {
                    id
                    validTo
                    agreedFrom
                    tariff {
                        ... on StandardTariff {
                            id
                            displayName
                            standingCharge
                            isExport
                            unitRate
                        }
                        ... on DayNightTariff {
                            id
                            displayName
                            fullName
                            standingCharge
                            isExport
                            dayRate
                            nightRate
                        }
                        ... on ThreeRateTariff {
                            id
                            displayName
                            standingCharge
                            isExport
                            dayRate
                            nightRate
                            offPeakRate
                        }
                        ... on HalfHourlyTariff {
                            id
                            displayName
                            standingCharge
                            isExport
                            unitRates {
                                validFrom
                                validTo
                                value
                            }
                        }
                        ... on PrepayTariff {
                            id
                            displayName
                            description
                            standingCharge
                            isExport
                            unitRate
                        }
                    }
                }
            }
        }
        """)
        return query
