from django.conf import settings
from django.db.utils import OperationalError, ProgrammingError

from market.models import Instrument


def market_navigation(request):
    try:
        instruments = Instrument.objects.filter(active=True)
        return {"instruments_navigation": instruments, "development_mode": settings.DEBUG}
    except (OperationalError, ProgrammingError):
        return {"instruments_navigation": (), "development_mode": settings.DEBUG}
