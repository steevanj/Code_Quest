from django.conf import settings
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from missions.curriculum import get_mission
from missions.preview import preview_checks

from .engine import FILES, analyze


def read_files(data):
    """Validate the {filename: source} payload the editor sends."""
    files = data.get("files")
    if not isinstance(files, dict):
        raise ValidationError({"files": "Expected an object mapping file names to source code."})
    clean = {}
    for name in FILES:
        text = files.get(name, "")
        if not isinstance(text, str):
            raise ValidationError({"files": f"{name} must be a string."})
        if len(text) > settings.MAX_SOURCE_CHARS:
            raise ValidationError({"files": f"{name} is too large."})
        clean[name] = text
    return clean


class AnalyzeView(APIView):
    """Static analysis of the editor contents. Called (debounced) while the learner types."""

    def post(self, request):
        files = read_files(request.data)
        result = analyze(files)
        mission = get_mission(request.data.get("mission_id"))
        if mission:
            result["checks"] = preview_checks(mission["checks"], result)
        return Response(result)
