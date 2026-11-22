"""Entity types detected by the anonymization module; each type is also the placeholder prefix."""

from enum import StrEnum


class Entity(StrEnum):
    # identifiers (exact spans)
    PERSON = "PERSON"
    PESEL = "PESEL"
    ID_CARD = "ID_CARD"
    PASSPORT = "PASSPORT"
    NIP = "NIP"
    BIRTH_DATE = "BIRTH_DATE"
    BIRTH_PLACE = "BIRTH_PLACE"
    ADDRESS = "ADDRESS"
    PHONE = "PHONE"
    EMAIL = "EMAIL"
    BANK_ACCOUNT = "BANK_ACCOUNT"
    LAND_REGISTER = "LAND_REGISTER"
    PLOT = "PLOT"
    VEHICLE_PLATE = "VEHICLE_PLATE"
    # special categories and protected secrets (whole sentence is flagged)
    HEALTH = "HEALTH"
    FAMILY = "FAMILY"
    FINANCES = "FINANCES"
    SOCIAL_BENEFITS = "SOCIAL_BENEFITS"
    BELIEFS = "BELIEFS"
    MEMBERSHIP = "MEMBERSHIP"
    ETHNICITY = "ETHNICITY"
    SEXUAL_ORIENTATION = "SEXUAL_ORIENTATION"
    CRIMINAL_RECORD = "CRIMINAL_RECORD"
    CONFIDENTIAL = "CONFIDENTIAL"


SENTENCE_ENTITIES = frozenset(
    {
        Entity.HEALTH,
        Entity.FAMILY,
        Entity.FINANCES,
        Entity.SOCIAL_BENEFITS,
        Entity.BELIEFS,
        Entity.MEMBERSHIP,
        Entity.ETHNICITY,
        Entity.SEXUAL_ORIENTATION,
        Entity.CRIMINAL_RECORD,
        Entity.CONFIDENTIAL,
    }
)
