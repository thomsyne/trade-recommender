import hashlib

from django.conf import settings
from django.db.utils import OperationalError, ProgrammingError

from market.models import Instrument


def market_navigation(request):
    try:
        instruments = Instrument.objects.filter(active=True)
        return {"instruments_navigation": instruments, "development_mode": settings.DEBUG}
    except (OperationalError, ProgrammingError):
        return {"instruments_navigation": (), "development_mode": settings.DEBUG}


def static_asset_version(request):
    digest = hashlib.sha256()
    for path in (
        settings.BASE_DIR / "dashboard/static/dashboard/app.css",
        settings.BASE_DIR / "dashboard/static/dashboard/app.js",
    ):
        digest.update(path.read_bytes())
    return {"static_asset_version": digest.hexdigest()[:12]}
