from django.urls import include, path

urlpatterns = [
    path("api/", include("analyzer.urls")),
    path("api/", include("missions.urls")),
    path("api/sandbox/", include("runner.urls")),
]
