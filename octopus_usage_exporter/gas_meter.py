from gql import gql
from energy_meter import energy_meter

class gas_meter(energy_meter):
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
            gasAgreement(id: $agreementId) {
                validTo
                isRevoked
                id
                validFrom
                ... on GasAgreementType {
                    id
                    isRevoked
                    tariff {
                        id
                        displayName
                        fullName
                        standingCharge
                        isExport
                        unitRate
                    }
                }
            }
        }
        """)
        return query
