from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from analyzer.views import read_files

from . import sandbox
from .fixtures import SAMPLE_CATALOG

METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


class StateView(APIView):
    """Applied schema, rows and migration files — no code is executed."""

    def get(self, request):
        return Response(sandbox.state(request.query_params.get("session")))


class MigrateView(APIView):
    def post(self, request):
        return Response(sandbox.migrate(request.data.get("session"), read_files(request.data)))


class RequestView(APIView):
    """Send one HTTP request through the learner's app and return the traced lifecycle."""

    def post(self, request):
        method = str(request.data.get("method", "GET")).upper()
        path = request.data.get("path", "")
        if method not in METHODS:
            raise ValidationError({"method": "Unsupported HTTP method."})
        if not isinstance(path, str) or not path.startswith("/") or len(path) > 500:
            raise ValidationError({"path": "Path must start with '/'."})
        return Response(sandbox.request(request.data.get("session"), read_files(request.data), method, path,
                                        request.data.get("body")))


class SeedView(APIView):
    def post(self, request):
        return Response(sandbox.seed(request.data.get("session"), read_files(request.data), SAMPLE_CATALOG))


class ResetView(APIView):
    def post(self, request):
        return Response(sandbox.reset(request.data.get("session")))
