"""A4: seed `assets` and approved `condition_records`: Highway 401 structures inside Toronto, Ontario bridge conditions file.

Source: Ontario Ministry of Transportation, Bridge conditions, https://data.ontario.ca/dataset/bridge-conditions
(file bridge_condition_open_data_2020_en.csv, 2021-06-09, sha256 642cd08d...a17; see ~/hackathon-data/SOURCES.md).
Licence: Open Government Licence - Ontario. Attribution: "Contains information licensed under the Open
Government Licence - Ontario."

Filter: HIGHWAY NAME == "401", CATEGORY == "Bridge" (culverts are excluded) and LATITUDE/LONGITUDE inside
TORONTO_BOX (an approximate box; it can include structures just over the city line). Rows missing any REQUIRED
field are skipped (198 rows load). deck_area = deck length x total width, rounded to 2 dp: it is derived, not a
source column, and the "area" label is ours. The Gardiner is city-owned and not in this provincial file. The per-year BCI columns (2000-2020) are
not loaded: nothing in the demo reads a rating history. One approved condition record per asset: CURRENT BCI
at the year of LAST INSPECTION DATE.

Seeding runs outside guarded_call. Upserts by `_id`, so a rerun writes the same documents. After upserting, `load` deletes region `r1` assets that are no
longer in the loaded set, and their seed condition records (`<asset_id>:<year>`).
"""
import csv
import os
import re
from datetime import datetime

import contracts
import db as dbmod

ONTARIO_PATH = os.environ.get(
    "ONTARIO_BRIDGES_PATH",
    os.path.expanduser("~/hackathon-data/ontario-bridge-conditions/bridge_condition_open_data_2020_en.csv"),
)
AREA = "TORONTO"  # stored in Asset.county; the file's COUNTY column has no Toronto value
HIGHWAY = "401"
CATEGORY = "Bridge"
REQUIRED = ("ID (SITE N°)", "LATITUDE", "LONGITUDE", "CURRENT BCI", "YEAR BUILT", "DECK / CULVERTS LENGTH (m)",
            "WIDTH TOTAL (m)", "LAST INSPECTION DATE")
TORONTO_BOX = (43.58, 43.86, -79.64, -79.11)  # lat min, lat max, lon min, lon max
REGION = "r1"
APPROVED = contracts.ConditionStatus.__args__[1]


def area_rows(path: str):
    lat0, lat1, lon0, lon1 = TORONTO_BOX
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if (r["HIGHWAY NAME"].strip() == HIGHWAY and r["CATEGORY"].strip() == CATEGORY and all(r[k].strip() for k in REQUIRED)
                    and lat0 <= float(r["LATITUDE"]) <= lat1 and lon0 <= float(r["LONGITUDE"]) <= lon1):
                yield r


def load(db, path: str = ONTARIO_PATH) -> int:
    loaded = set()
    for r in area_rows(path):
        a = contracts.Asset(
            id=r["ID (SITE N°)"].strip(), region=REGION, county=AREA, year_built=int(r["YEAR BUILT"]),
            deck_area=round(float(r["DECK / CULVERTS LENGTH (m)"]) * float(r["WIDTH TOTAL (m)"]), 2),
        )
        rec = contracts.ConditionRecord(
            asset_id=a.id, rating=float(r["CURRENT BCI"]),
            year=datetime.strptime(r["LAST INSPECTION DATE"], "%m/%d/%Y").year, status=APPROVED,
        )
        db.assets.replace_one({"_id": a.id}, a.model_dump(by_alias=True), upsert=True)
        db.condition_records.replace_one({"_id": f"{a.id}:{rec.year}"}, rec.model_dump(), upsert=True)
        loaded.add(a.id)
    removed = [d["_id"] for d in db.assets.find({"region": REGION, "_id": {"$nin": list(loaded)}}, {"_id": 1})]
    db.assets.delete_many({"_id": {"$in": removed}})
    for asset_id in removed:
        db.condition_records.delete_many({"asset_id": asset_id, "_id": {"$regex": f"^{re.escape(asset_id)}:[0-9]{{4}}$"}})
    return len(loaded)


if __name__ == "__main__":
    print(load(dbmod.get_db()))
