from functools import wraps

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden


def owner_required(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            return HttpResponseForbidden("Owner access required")
        return view(request, *args, **kwargs)

    return wrapped
