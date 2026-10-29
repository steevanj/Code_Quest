from django.urls import path

from . import views

urlpatterns = [
    path("state/", views.StateView.as_view(), name="sandbox-state"),
    path("migrate/", views.MigrateView.as_view(), name="sandbox-migrate"),
    path("request/", views.RequestView.as_view(), name="sandbox-request"),
    path("seed/", views.SeedView.as_view(), name="sandbox-seed"),
    path("reset/", views.ResetView.as_view(), name="sandbox-reset"),
]
