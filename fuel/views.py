from urllib.parse import urlencode

from django.shortcuts import render
from django.urls import reverse
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import APIView

from fuel.serializers import RouteQuerySerializer
from fuel.services.planner import plan_trip


class RouteView(APIView):
    def get(self, request):
        query = RouteQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        plan = plan_trip(**query.validated_data)
        params = {"start": plan["start"]["query"], "finish": plan["finish"]["query"], **plan["options"]}
        plan["map_url"] = request.build_absolute_uri(f"{reverse('route-map')}?{urlencode(params)}")
        return Response(plan)


def route_map(request):
    context = {"json_url": f"{reverse('route')}?{request.GET.urlencode()}"}
    try:
        query = RouteQuerySerializer(data=request.GET)
        query.is_valid(raise_exception=True)
        context["plan"] = plan_trip(**query.validated_data)
    except APIException as exc:
        context.update(error=_message(exc.detail), status_code=exc.status_code)
        return render(request, "fuel/map.html", context, status=exc.status_code)
    return render(request, "fuel/map.html", context)


def _message(detail) -> str:
    """One readable line from a DRF error detail, which may be a string or a field-to-messages dict."""
    if isinstance(detail, dict):
        return " ".join(f"{field}: {' '.join(map(str, messages))}" for field, messages in detail.items())
    return str(detail)
