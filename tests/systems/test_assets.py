from pathlib import Path

import pytest

import contracts
from systems import assets

pytestmark = pytest.mark.skipif(not Path(assets.ONTARIO_PATH).exists(), reason="Ontario bridges file absent")


def test_load_county_matches_file_and_is_idempotent(tdb):
    expected = sum(1 for _ in assets.county_rows(assets.ONTARIO_PATH, assets.COUNTY))
    assert 30 <= expected <= 300
    assert assets.load(tdb) == expected
    assets.load(tdb)
    assert tdb.assets.count_documents({"county": assets.COUNTY, "region": "r1"}) == expected
    approved = contracts.ConditionStatus.__args__[1]
    assert tdb.condition_records.count_documents({"status": approved}) == expected
    contracts.Asset.model_validate(tdb.assets.find_one())
