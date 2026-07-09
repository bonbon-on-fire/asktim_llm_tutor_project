import pytest
from utils.uploads import enforce_combined_cap, UploadValidationError, MAX_ATTACHMENTS_PER_MESSAGE


def test_cap_value():
    assert MAX_ATTACHMENTS_PER_MESSAGE == 3


def test_within_cap_ok():
    enforce_combined_cap(2, 1)  # 3 total — fine


def test_over_cap_raises():
    with pytest.raises(UploadValidationError):
        enforce_combined_cap(2, 2)  # 4 total
