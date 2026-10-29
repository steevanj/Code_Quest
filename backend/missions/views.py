from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from analyzer.views import read_files
from runner import sandbox

from .curriculum import curriculum, get_mission


class CurriculumView(APIView):
    def get(self, request):
        return Response(curriculum())


class MissionCheckView(APIView):
    """Verify a mission in a throwaway copy of the learner's project."""

    def post(self, request, mission_id):
        mission = get_mission(mission_id)
        if not mission:
            raise NotFound("Unknown mission.")
        files = read_files(request.data)
        result = sandbox.run_checks(request.data.get("session"), files, mission["checks"])
        results = result.get("results", [])
        result["passed"] = bool(results) and all(r["passed"] for r in results)
        return Response(result)
