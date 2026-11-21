from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    """Report that the API process is up. Used by Docker, monitoring and CI.

    Public on purpose: it reveals nothing beyond "the service is running".
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []
    http_method_names = ["get", "head", "options"]

    def get(self, request: Request, version: str) -> Response:
        return Response({"status": "ok"})
