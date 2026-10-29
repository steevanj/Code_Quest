from django.urls import path

from .views import CurriculumView, MissionCheckView

urlpatterns = [
    path("missions/", CurriculumView.as_view(), name="curriculum"),
    path("missions/<slug:mission_id>/check/", MissionCheckView.as_view(), name="mission-check"),
]
