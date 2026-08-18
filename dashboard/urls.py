from django.urls import path

from dashboard import views

urlpatterns = [
    path("", views.today, name="today"),
    path("markets/<str:code>/", views.market_detail, name="market-detail"),
    path("operations/", views.operations, name="operations"),
]
