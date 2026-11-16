from django.db import models


class FuelStation(models.Model):
    """A truck stop from the supplied price list, with the coordinates worked out for it."""

    opis_id = models.PositiveIntegerField(primary_key=True)
    name = models.CharField(max_length=120)
    address = models.CharField(max_length=200)
    city = models.CharField(max_length=80)
    state = models.CharField(max_length=2)
    price = models.FloatField(help_text="Dollars per gallon; the lowest listed for this station.")
    lat = models.FloatField()
    lon = models.FloatField()
    located_by = models.CharField(
        max_length=10, help_text="How the coordinates were found: 'exit' is precise, 'town' is approximate."
    )

    def __str__(self):
        return f"{self.name}, {self.city}, {self.state}"
