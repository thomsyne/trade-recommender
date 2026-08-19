from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from market.models import SourceRegistry
from operations.models import ScheduledJob
from research.models import MacroSeries, ProviderEvaluation, SourcePolicy

SOURCES = (
    {
        "slug": "bank-of-canada",
        "name": "Bank of Canada",
        "jurisdiction": "CA",
        "currency": "CAD",
        "base_url": "https://www.bankofcanada.ca/",
        "terms_url": "https://www.bankofcanada.ca/terms/",
        "hosts": ["www.bankofcanada.ca"],
        "types": ["application/json", "application/rss+xml", "application/xml", "text/xml"],
        "feed": "https://www.bankofcanada.ca/content_type/press-releases/feed/",
    },
    {
        "slug": "federal-reserve",
        "name": "Federal Reserve Board",
        "jurisdiction": "US",
        "currency": "USD",
        "base_url": "https://www.federalreserve.gov/",
        "terms_url": "https://www.federalreserve.gov/website-linking-policies.htm",
        "hosts": ["www.federalreserve.gov"],
        "types": ["application/rss+xml", "application/xml", "text/xml"],
        "feed": "https://www.federalreserve.gov/feeds/press_monetary.xml",
    },
    {
        "slug": "fred",
        "name": "Federal Reserve Bank of St. Louis FRED",
        "jurisdiction": "US",
        "currency": "USD",
        "base_url": "https://fred.stlouisfed.org/",
        "terms_url": "https://fred.stlouisfed.org/legal/",
        "hosts": ["fred.stlouisfed.org"],
        "types": ["application/csv", "text/csv"],
    },
    {
        "slug": "european-central-bank",
        "name": "European Central Bank",
        "jurisdiction": "EU",
        "currency": "EUR",
        "base_url": "https://www.ecb.europa.eu/",
        "terms_url": "https://www.ecb.europa.eu/services/disclaimer/html/index.en.html",
        "hosts": ["www.ecb.europa.eu", "data-api.ecb.europa.eu"],
        "types": ["application/rss+xml", "application/xml", "text/xml", "text/csv"],
        "feed": "https://www.ecb.europa.eu/rss/press.html",
    },
    {
        "slug": "bank-of-england",
        "name": "Bank of England",
        "jurisdiction": "GB",
        "currency": "GBP",
        "base_url": "https://www.bankofengland.co.uk/",
        "terms_url": "https://www.bankofengland.co.uk/legal",
        "hosts": ["www.bankofengland.co.uk"],
        "types": [
            "application/rss+xml",
            "application/xml",
            "text/xml",
            "application/csv",
            "text/csv",
        ],
        "feed": "https://www.bankofengland.co.uk/rss/news",
    },
)

SERIES = (
    {
        "policy": "bank-of-canada",
        "code": "CA_POLICY_RATE",
        "provider_series_id": "V39079",
        "label": "Target for the overnight rate",
        "parser": MacroSeries.Parser.BOC_VALET,
        "url": "https://www.bankofcanada.ca/valet/observations/V39079/json?recent=120",
    },
    {
        "policy": "fred",
        "code": "US_POLICY_TARGET_UPPER",
        "provider_series_id": "DFEDTARU",
        "label": "Federal funds target range — upper limit",
        "parser": MacroSeries.Parser.FRED_CSV,
        "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTARU",
    },
    {
        "policy": "european-central-bank",
        "code": "EU_DEPOSIT_FACILITY_RATE",
        "provider_series_id": "FM.D.U2.EUR.4F.KR.DFR.LEV",
        "label": "ECB deposit facility rate",
        "parser": MacroSeries.Parser.ECB_CSV,
        "url": "https://data-api.ecb.europa.eu/service/data/FM/D.U2.EUR.4F.KR.DFR.LEV?format=csvdata&lastNObservations=120",
    },
    {
        "policy": "bank-of-england",
        "code": "GB_BANK_RATE",
        "provider_series_id": "IUDBEDR",
        "label": "Official Bank Rate",
        "parser": MacroSeries.Parser.BOE_CSV,
        "url": "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp?csv.x=yes&Datefrom=01/Jan/2025&Dateto=now&SeriesCodes=IUDBEDR&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N",
    },
)


class Command(BaseCommand):
    help = "Seed verified official research sources and durable collection schedules"

    def handle(self, *args, **options):
        policies = {}
        for item in SOURCES:
            source, _ = SourceRegistry.objects.update_or_create(
                name=item["name"],
                defaults={
                    "tier": SourceRegistry.Tier.PRIMARY,
                    "base_url": item["base_url"],
                    "terms_url": item["terms_url"],
                    "acquisition_method": "Official HTTPS API/RSS",
                    "retention_policy": "Bounded immutable official-source snapshots; private research only.",
                    "llm_processing_allowed": False,
                    "attribution_required": True,
                    "deletion_policy": "Remove if official terms or owner policy requires deletion.",
                    "export_policy": "No redistribution of raw source bodies.",
                    "enabled": True,
                },
            )
            policy, _ = SourcePolicy.objects.update_or_create(
                slug=item["slug"],
                defaults={
                    "source": source,
                    "jurisdiction": item["jurisdiction"],
                    "currency": item["currency"],
                    "allowed_hosts": item["hosts"],
                    "allowed_content_types": item["types"],
                    "max_response_bytes": 2_000_000,
                    "rights_url": item["terms_url"],
                    "retention_class": "official-public-record",
                    "full_text_allowed": False,
                    "state": SourcePolicy.State.ENABLED,
                    "quality_note": "Official endpoint verified; article full text is not collected.",
                },
            )
            policies[item["slug"]] = policy
            if feed := item.get("feed"):
                _upsert_job(
                    f"Research feed — {item['name']}",
                    "research.ingest_feed",
                    {"source": item["slug"], "url": feed},
                    21_600,
                )
        for item in SERIES:
            series, _ = MacroSeries.objects.update_or_create(
                code=item["code"],
                defaults={
                    "source_policy": policies[item["policy"]],
                    "provider_series_id": item["provider_series_id"],
                    "label": item["label"],
                    "unit": "percent",
                    "frequency": "business daily",
                    "parser": item["parser"],
                    "url": item["url"],
                    "enabled": True,
                    "point_in_time_note": "Provider gives observation date, not release timestamp; availability is conservatively the first retrieval time.",
                },
            )
            _upsert_job(
                f"Research macro — {series.label}",
                "research.ingest_macro",
                {"series": series.code},
                86_400,
            )
        ProviderEvaluation.objects.update_or_create(
            category="economic-calendar",
            provider="Trading Economics",
            defaults={
                "status": ProviderEvaluation.Status.CANDIDATE,
                "evidence_url": "https://docs.tradingeconomics.com/",
                "pricing_status": "Unverified — no subscription selected",
                "timestamp_semantics": "To be measured against official release timestamps",
                "revision_support": "To be tested during a bounded trial",
                "retention_rights": "Terms and API retention rights require review",
                "reliability_result": "Not measured",
                "next_check": "Compare release latency, revisions, coverage, rate limits, and private retention before purchase.",
            },
        )
        self.stdout.write(self.style.SUCCESS("official research registry ready"))


def _upsert_job(name, task_name, parameters, interval):
    job, _ = ScheduledJob.objects.get_or_create(
        name=name,
        defaults={
            "task_name": task_name,
            "parameters": parameters,
            "interval_seconds": interval,
            "next_run_at": timezone.now() + timedelta(seconds=interval),
            "enabled": True,
        },
    )
    job.task_name = task_name
    job.parameters = parameters
    job.interval_seconds = interval
    job.enabled = True
    job.save(update_fields=("task_name", "parameters", "interval_seconds", "enabled"))
