from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.shortcuts import redirect
from django.urls import include, path, reverse

from dashboard.auth import OwnerLoginView
from dashboard.views import health, live, ready


def admin_login(request, extra_context=None):
    return redirect(f"{reverse('login')}?next={request.get_full_path()}")


admin.site.login = admin_login

urlpatterns = [
    path("health/", health, name="health"),
    path("health/live/", live, name="live"),
    path("health/ready/", ready, name="ready"),
    path("admin/", admin.site.urls),
    path(
        "login/",
        OwnerLoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("", include("dashboard.urls")),
]
