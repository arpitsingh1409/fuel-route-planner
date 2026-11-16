from rest_framework import serializers


class RouteQuerySerializer(serializers.Serializer):
    start = serializers.CharField(max_length=200)
    finish = serializers.CharField(max_length=200)
    start_fuel_gallons = serializers.FloatField(min_value=0, max_value=50, default=0)
    stop_cost = serializers.FloatField(min_value=0, max_value=100, default=0)
