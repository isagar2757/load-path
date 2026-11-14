"""A4: seed `assets` and approved `condition_records` from one county of Ontario's bridge conditions file.

Source: Ontario Ministry of Transportation, Bridge conditions, https://data.ontario.ca/dataset/bridge-conditions
(file bridge_condition_open_data_2020_en.csv, 2021-06-09, sha256 642cd08d...a17; see ~/hackathon-data/SOURCES.md).
Licence: Open Government Licence - Ontario. Attribution: "Contains information licensed under the Open
Government Licence - Ontario."

Filter: COUNTY == "WATERLOO" (106 rows of 5,053). Fill rates in that set: ID, YEAR BUILT, DECK / CULVERTS
LENGTH (m), WIDTH TOTAL (m), CURRENT BCI, LAST INSPECTION DATE 106/106. The per-year BCI columns (2000-2020) are
not loaded: nothing in the demo reads a rating history. One approved condition record per asset: CURRENT BCI
at the year of LAST INSPECTION DATE.

Seeding runs outside guarded_call. Upserts by `_id`, so a rerun writes the same documents.
"""
import csv
import os
from datetime import datetime

import contracts
import db as dbmod

ONTARIO_PATH = os.environ.get(
    "ONTARIO_BRIDGES_PATH",
    os.path.expanduser("~/hackathon-data/ontario-bridge-conditions/bridge_condition_open_data_2020_en.csv"),
)
COUNTY = "WATERLOO"
REGION = "r1"
APPROVED = contracts.ConditionStatus.__args__[1]


def county_rows(path: str, county: str):
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["COUNTY"] == county:
                yield r


def load(db, path: str = ONTARIO_PATH) -> int:
    n = 0
    for r in county_rows(path, COUNTY):
        a = contracts.Asset(
            id=r["ID (SITE N°)"].strip(), region=REGION, county=COUNTY, year_built=int(r["YEAR BUILT"]),
            deck_area=float(r["DECK / CULVERTS LENGTH (m)"]) * float(r["WIDTH TOTAL (m)"]),
        )
        rec = contracts.ConditionRecord(
            asset_id=a.id, rating=float(r["CURRENT BCI"]),
            year=datetime.strptime(r["LAST INSPECTION DATE"], "%m/%d/%Y").year, status=APPROVED,
        )
        db.assets.replace_one({"_id": a.id}, a.model_dump(by_alias=True), upsert=True)
        db.condition_records.replace_one({"_id": f"{a.id}:{rec.year}"}, rec.model_dump(), upsert=True)
        n += 1
    return n


if __name__ == "__main__":
    print(load(dbmod.get_db(contracts.DB_NAME)))
