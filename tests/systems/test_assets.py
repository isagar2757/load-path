from pathlib import Path

import pytest

import contracts
from systems import assets

pytestmark = pytest.mark.skipif(not Path(assets.ONTARIO_PATH).exists(), reason="Ontario bridges file absent")


def test_load_area_matches_file_and_is_idempotent(tdb):
    expected = sum(1 for _ in assets.area_rows(assets.ONTARIO_PATH))
    assert 30 <= expected <= 300
    assert assets.load(tdb) == expected
    assets.load(tdb)
    assert tdb.assets.count_documents({"county": assets.AREA, "region": "r1"}) == expected
    approved = contracts.ConditionStatus.__args__[1]
    assert tdb.condition_records.count_documents({"status": approved}) == expected
    contracts.Asset.model_validate(tdb.assets.find_one())


def test_load_bridges_only_rounds_area_and_removes_stale(tdb):
    bridge_ids = {r["ID (SITE N°)"].strip() for r in assets.area_rows(assets.ONTARIO_PATH)}
    assert all(r["CATEGORY"] == "Bridge" for r in assets.area_rows(assets.ONTARIO_PATH))
    approved = contracts.ConditionStatus.__args__[1]
    tdb.assets.insert_one(contracts.Asset(id="STALE1", region="r1", county=assets.AREA, year_built=1970,
                                          deck_area=100.0).model_dump(by_alias=True))
    tdb.condition_records.insert_one({"_id": "STALE1:2019", **contracts.ConditionRecord(
        asset_id="STALE1", rating=60.0, year=2019, status=approved).model_dump()})
    assert assets.load(tdb) == len(bridge_ids)
    assert tdb.assets.count_documents({"region": "r1"}) == len(bridge_ids)
    assert tdb.assets.count_documents({"_id": "STALE1"}) == 0
    assert tdb.condition_records.count_documents({"asset_id": "STALE1"}) == 0
    assert tdb.condition_records.count_documents({}) == len(bridge_ids)
    assert all(a["deck_area"] == round(a["deck_area"], 2) for a in tdb.assets.find())
