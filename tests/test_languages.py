from autodub.languages import normalize_code, primary_subtag
from autodub.errors import InputError
import pytest


def test_normalize_basic():
    assert normalize_code("EN") == "en"
    assert normalize_code("tr") == "tr"
    assert normalize_code("pt-br") == "pt-BR"


def test_primary_subtag():
    assert primary_subtag("pt-BR") == "pt"


@pytest.mark.parametrize("bad", ["", "  ", "e", "english1", "1", "toolong"])
def test_invalid_codes(bad):
    with pytest.raises(InputError):
        normalize_code(bad)
