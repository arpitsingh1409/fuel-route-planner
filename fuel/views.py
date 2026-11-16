from urllib.parse import urlencode

from django.http import HttpResponse
from django.urls import reverse
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
    # Placeholder until the map page is built.
    return HttpResponse(status=501)
