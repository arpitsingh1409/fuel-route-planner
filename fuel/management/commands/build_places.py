"""Build data/us_places.csv, the list used to resolve "City, ST" without an outside call.

Source: US Census Bureau Gazetteer, places file (public domain).
"""

import csv
import io
import re
import zipfile

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
    "2025_Gazetteer/2025_Gaz_place_national.zip"
)
TYPE_SUFFIX = re.compile(
    r"\s+(city and borough|consolidated government|metropolitan government|metro government"
    r"|unified government|urban county|municipality|comunidad|zona urbana|borough|village"
    r"|city|town|CDP)$"
)


def clean_name(census_name: str) -> str:
    """'Big Cabin town' -> 'Big Cabin'; 'Indianapolis city (balance)' -> 'Indianapolis'."""
    return TYPE_SUFFIX.sub("", census_name.strip().removesuffix(" (balance)"))


class Command(BaseCommand):
    help = __doc__

    def handle(self, *args, **options):
        archive = settings.DATA_DIR / "raw" / "census" / URL.rsplit("/", 1)[1]
        if not archive.exists():
            archive.parent.mkdir(parents=True, exist_ok=True)
            response = requests.get(URL, timeout=60)
            response.raise_for_status()
            archive.write_bytes(response.content)

        with zipfile.ZipFile(archive) as z:
            text = z.read(z.namelist()[0]).decode("utf-8")
        rows = []
        for r in csv.DictReader(io.StringIO(text), delimiter="|"):
            r = {k.strip(): v.strip() for k, v in r.items()}
            name = clean_name(r["NAME"])
            place = (float(r["ALAND"]), r["USPS"], r["INTPTLAT"], r["INTPTLONG"])
            rows.append((0, name, *place))
            # 'Nashville-Davidson' and 'Louisville/Jefferson County' are known by their first part.
            short = re.split(r"[-/]", name)[0].strip()
            if short != name:
                rows.append((1, short, *place))

        # The lookup keeps the first row it sees for a name, so order decides ties:
        # real names before short forms, then the larger place first.
        rows.sort(key=lambda row: (row[0], -row[2]))
        out = settings.DATA_DIR / "us_places.csv"
        with out.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["name", "state", "lat", "lon"])
            writer.writerows((name, state, lat, lon) for _, name, _, state, lat, lon in rows)
        self.stdout.write(f"Wrote {len(rows)} places to {out}")
