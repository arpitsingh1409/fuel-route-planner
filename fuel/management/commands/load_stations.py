"""Load data/stations.csv into the station table, replacing whatever is there."""

import csv

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from fuel.models import FuelStation
from fuel.services import stations


class Command(BaseCommand):
    help = __doc__

    def handle(self, *args, **options):
        with (settings.DATA_DIR / "stations.csv").open(newline="") as f:
            rows = [FuelStation(**row) for row in csv.DictReader(f)]
        with transaction.atomic():
            FuelStation.objects.all().delete()
            FuelStation.objects.bulk_create(rows)
        stations.clear_cache()
        self.stdout.write(f"Loaded {len(rows)} stations")
