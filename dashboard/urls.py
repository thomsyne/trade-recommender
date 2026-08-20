from django.urls import path

from dashboard import views

urlpatterns = [
    path("", views.today, name="today"),
    path("calibration/", views.calibration, name="calibration"),
    path("paper/", views.paper_trades, name="paper-trades"),
    path("research/", views.research, name="research"),
    path("markets/<str:code>/", views.market_detail, name="market-detail"),
    path("operations/", views.operations, name="operations"),
]
