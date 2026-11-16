"""Errors the API can return. DRF turns each into a JSON body with the given status."""

from rest_framework.exceptions import APIException


class LocationNotFound(APIException):
    status_code = 400
    default_detail = "Location not found."
    default_code = "location_not_found"


class UpstreamUnavailable(APIException):
    status_code = 503
    default_detail = "A map service this API depends on is unavailable. Please try again shortly."
    default_code = "upstream_unavailable"


class NoRouteFound(APIException):
    status_code = 422
    default_detail = "No drivable route was found between the two locations."
    default_code = "no_route"


class NoFeasiblePlan(APIException):
    status_code = 422
    default_detail = (
        "No fuel plan is possible: part of the route has no station within the vehicle's range."
    )
    default_code = "no_feasible_plan"
