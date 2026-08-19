from market.models import SourceRegistry
from research.models import SourcePolicy


def source_policy(**changes):
    source = SourceRegistry.objects.create(
        name=changes.pop("name", "Test official source"),
        tier=SourceRegistry.Tier.PRIMARY,
        base_url="https://official.example/",
        terms_url="https://official.example/terms",
        acquisition_method="Test HTTPS",
        retention_policy="Test-only bounded snapshots",
        enabled=True,
    )
    values = {
        "source": source,
        "slug": "test-official",
        "jurisdiction": "CA",
        "currency": "CAD",
        "allowed_hosts": ["official.example"],
        "allowed_content_types": ["application/rss+xml", "text/csv"],
        "max_response_bytes": 10_000,
        "rights_url": "https://official.example/terms",
        "state": SourcePolicy.State.ENABLED,
    }
    values.update(changes)
    return SourcePolicy.objects.create(**values)
