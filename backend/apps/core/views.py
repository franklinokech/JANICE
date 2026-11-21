from django.db import DatabaseError, connection
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    """Report whether the API process is up and can reach its database.

    Used by Docker, monitoring and CI. Public on purpose: it reveals nothing
    beyond "the service is running" and "the database answers".
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []
    http_method_names = ["get", "head", "options"]

    def get(self, request: Request, version: str) -> Response:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except DatabaseError:
            return Response(
                {"status": "error", "database": "unavailable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({"status": "ok", "database": "ok"})
