from django.urls import path

from dashboard import views

urlpatterns = [
    path("", views.today, name="today"),
    path("inbox/", views.inbox, name="inbox"),
    path(
        "portfolio/cohorts/<int:cohort_id>/select/",
        views.select_cohort,
        name="select-cohort",
    ),
    path("calibration/", views.calibration, name="calibration"),
    path(
        "calibration/experiments/<int:era_id>/assessments/<int:assessment_id>/decide/",
        views.decide_experiment,
        name="decide-experiment",
    ),
    path("exposure/", views.exposure, name="exposure"),
    path("paper/", views.paper_trades, name="paper-trades"),
    path("research/", views.research, name="research"),
    path("reviews/", views.reviews, name="reviews"),
    path(
        "reviews/hypotheses/<int:hypothesis_id>/authorize/",
        views.authorize_challenger,
        name="authorize-challenger",
    ),
    path("markets/<str:code>/", views.market_detail, name="market-detail"),
    path("operations/", views.operations, name="operations"),
]
