import pytest

from anonymization.checksums import is_valid_id_card, is_valid_nip, is_valid_nrb


@pytest.mark.parametrize("value", ["5261040828", "526-104-08-28", "526-10-40-828"])
def test_valid_nip(value):
    assert is_valid_nip(value)


@pytest.mark.parametrize("value", ["5261040827", "123456789", "52610408280"])
def test_invalid_nip(value):
    assert not is_valid_nip(value)


def test_id_card():
    assert is_valid_id_card("ABA300000")
    assert is_valid_id_card("aba 300000")
    assert not is_valid_id_card("ABA400000")
    assert not is_valid_id_card("AB3000000")


def test_nrb():
    assert is_valid_nrb("61 1090 1014 0000 0712 1981 2874")
    assert is_valid_nrb("PL61109010140000071219812874")
    assert not is_valid_nrb("61 1090 1014 0000 0712 1981 2875")
    assert not is_valid_nrb("61 1090 1014")
