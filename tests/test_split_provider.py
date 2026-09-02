"""Unit tests for the shared provider/model split helper."""
import pytest

from core.domain.policies.provider import split_provider_model


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("provider/model", ("provider", "model")),
        ("Provider/Model", ("provider", "Model")),
        ("  provider /  model  ", ("provider", "model")),
        ("provider/", ("provider", "")),
        ("/model", ("", "model")),
        ("provider", ("provider", None)),
        ("  Provider  ", ("provider", None)),
        ("", (None, None)),
        ("   ", (None, None)),
        (None, (None, None)),
        (123, (None, None)),
    ],
)
def test_split_provider_model(raw, expected):
    assert split_provider_model(raw) == expected
