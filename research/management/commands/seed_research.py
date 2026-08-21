from datetime import timedelta

from django.conf import settings
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
        "types": ["application/rss+xml", "application/xml", "text/xml", "text/html"],
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
        "types": [
            "application/rss+xml",
            "application/xml",
            "text/xml",
            "text/csv",
            "text/html",
        ],
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
            "text/html",
        ],
        "feed": "https://www.bankofengland.co.uk/rss/news",
    },
    {
        "slug": "statistics-canada",
        "name": "Statistics Canada",
        "jurisdiction": "CA",
        "currency": "CAD",
        "base_url": "https://www.statcan.gc.ca/",
        "terms_url": "https://open.canada.ca/en/open-government-licence-canada",
        "hosts": ["www150.statcan.gc.ca"],
        "types": ["application/json", "application/zip"],
    },
    {
        "slug": "us-bls",
        "name": "US Bureau of Labor Statistics",
        "jurisdiction": "US",
        "currency": "USD",
        "base_url": "https://www.bls.gov/",
        "terms_url": "https://www.bls.gov/bls/linksite.htm",
        "hosts": ["api.bls.gov"],
        "types": ["application/json"],
    },
    {
        "slug": "us-bea",
        "name": "US Bureau of Economic Analysis",
        "jurisdiction": "US",
        "currency": "USD",
        "base_url": "https://www.bea.gov/",
        "terms_url": "https://www.bea.gov/statement-commitment-scientific-integrity-bea",
        "hosts": ["apps.bea.gov"],
        "types": ["application/json"],
    },
    {
        "slug": "uk-ons",
        "name": "UK Office for National Statistics",
        "jurisdiction": "GB",
        "currency": "GBP",
        "base_url": "https://www.ons.gov.uk/",
        "terms_url": "https://www.ons.gov.uk/methodology/geography/licences",
        "hosts": ["www.ons.gov.uk"],
        "types": ["application/octet-stream", "text/csv", "application/rss+xml"],
    },
    {
        "slug": "eurostat",
        "name": "Eurostat",
        "jurisdiction": "EU",
        "currency": "EUR",
        "base_url": "https://ec.europa.eu/eurostat/",
        "terms_url": "https://ec.europa.eu/eurostat/about-us/policies/copyright",
        "hosts": ["ec.europa.eu"],
        "types": ["application/json", "text/plain"],
    },
    {
        "slug": "uk-land-registry",
        "name": "HM Land Registry UK HPI",
        "jurisdiction": "GB",
        "currency": "GBP",
        "base_url": "https://landregistry.data.gov.uk/",
        "terms_url": "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
        "hosts": ["landregistry.data.gov.uk"],
        "types": ["text/csv"],
    },
    {
        "slug": "eodhd-calendar",
        "name": "EODHD Economic Events",
        "jurisdiction": "ZZ",
        "currency": "XXX",
        "base_url": "https://eodhd.com/",
        "terms_url": "https://eodhd.com/financial-apis/terms-conditions",
        "hosts": ["eodhd.com"],
        "types": ["application/json"],
        "commercial": True,
        "acquisition_method": "Commercial HTTPS API",
        "retention_policy": "Bounded commercial snapshots for private research only.",
    },
    {
        "slug": "bbc-business",
        "name": "BBC Business",
        "jurisdiction": "ZZ",
        "currency": "XXX",
        "base_url": "https://www.bbc.com/business",
        "terms_url": "https://www.bbc.co.uk/usingthebbc/terms/",
        "hosts": ["feeds.bbci.co.uk"],
        "types": ["text/xml", "application/xml", "application/rss+xml"],
        "feed": "https://feeds.bbci.co.uk/news/business/rss.xml",
        "tier": SourceRegistry.Tier.ESTABLISHED,
        "llm_processing_allowed": True,
        "acquisition_method": "Public RSS feed",
        "retention_policy": "Bounded RSS metadata and supplied summaries; no article full text.",
    },
    {
        "slug": "cbc-business",
        "name": "CBC Business",
        "jurisdiction": "CA",
        "currency": "CAD",
        "base_url": "https://www.cbc.ca/news/business",
        "terms_url": "https://www.cbc.ca/aboutcbc/discover/termsofuse.html",
        "hosts": ["www.cbc.ca"],
        "types": ["text/xml", "application/xml", "application/rss+xml"],
        "feed": "https://www.cbc.ca/webfeed/rss/rss-business",
        "tier": SourceRegistry.Tier.ESTABLISHED,
        "llm_processing_allowed": True,
        "acquisition_method": "Public RSS feed",
        "retention_policy": "Bounded RSS metadata and supplied summaries; no article full text.",
    },
    {
        "slug": "guardian-business",
        "name": "The Guardian Business",
        "jurisdiction": "ZZ",
        "currency": "XXX",
        "base_url": "https://www.theguardian.com/business",
        "terms_url": "https://www.theguardian.com/help/terms-of-service",
        "hosts": ["www.theguardian.com"],
        "types": ["text/xml", "application/xml", "application/rss+xml"],
        "feed": "https://www.theguardian.com/business/rss",
        "tier": SourceRegistry.Tier.ESTABLISHED,
        "llm_processing_allowed": True,
        "acquisition_method": "Public RSS feed",
        "retention_policy": "Bounded RSS metadata and supplied summaries; no article full text.",
    },
    {
        "slug": "nyt-business",
        "name": "The New York Times Business",
        "jurisdiction": "ZZ",
        "currency": "XXX",
        "base_url": "https://www.nytimes.com/section/business",
        "terms_url": "https://help.nytimes.com/hc/en-us/articles/115014893428-Terms-of-service",
        "hosts": ["rss.nytimes.com"],
        "types": ["text/xml", "application/xml", "application/rss+xml"],
        "feed": "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
        "tier": SourceRegistry.Tier.ESTABLISHED,
        "llm_processing_allowed": True,
        "acquisition_method": "Public RSS feed",
        "retention_policy": "Bounded RSS metadata and supplied summaries; no article full text.",
    },
    {
        "slug": "coindesk",
        "name": "CoinDesk",
        "jurisdiction": "ZZ",
        "currency": "XXX",
        "base_url": "https://www.coindesk.com/",
        "terms_url": "https://www.coindesk.com/terms-of-use/",
        "hosts": ["www.coindesk.com"],
        "types": ["text/plain", "text/xml", "application/xml", "application/rss+xml"],
        "feed": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "tier": SourceRegistry.Tier.CONTEXTUAL,
        "llm_processing_allowed": True,
        "acquisition_method": "Public RSS feed",
        "retention_policy": "Bounded RSS metadata and supplied summaries; no article full text.",
    },
    {
        "slug": "world-bank-gold-datahub",
        "name": "World Bank gold prices via DataHub",
        "jurisdiction": "ZZ",
        "currency": "USD",
        "base_url": "https://datahub.io/core/gold-prices",
        "terms_url": "https://datahub.io/core/gold-prices",
        "hosts": ["datahub.io", "r2.datahub.io"],
        "types": ["text/csv"],
        "tier": SourceRegistry.Tier.ESTABLISHED,
        "acquisition_method": "Public curated HTTPS CSV",
        "retention_policy": "Bounded public dataset snapshot for private research.",
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
    {
        "policy": "statistics-canada",
        "code": "CA_CPI_YOY",
        "provider_series_id": "41690973",
        "label": "CPI inflation, all items",
        "indicator": MacroSeries.Indicator.CPI,
        "parser": MacroSeries.Parser.STATCAN_WDS,
        "method": "POST",
        "payload": [{"vectorId": 41690973, "latestN": 36}],
        "transform": MacroSeries.Transformation.YEAR_OVER_YEAR,
        "frequency": "monthly",
        "url": "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods",
    },
    {
        "policy": "statistics-canada",
        "code": "CA_UNEMPLOYMENT",
        "provider_series_id": "2062815",
        "label": "Unemployment rate",
        "indicator": MacroSeries.Indicator.UNEMPLOYMENT,
        "parser": MacroSeries.Parser.STATCAN_WDS,
        "method": "POST",
        "payload": [{"vectorId": 2062815, "latestN": 24}],
        "frequency": "monthly",
        "url": "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods",
    },
    {
        "policy": "statistics-canada",
        "code": "CA_REAL_GDP_GROWTH",
        "provider_series_id": "1594571783",
        "label": "Real GDP growth",
        "indicator": MacroSeries.Indicator.GDP,
        "parser": MacroSeries.Parser.STATCAN_WDS,
        "method": "POST",
        "payload": [{"vectorId": 1594571783, "latestN": 24}],
        "frequency": "quarterly",
        "url": "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods",
    },
    {
        "policy": "statistics-canada",
        "code": "CA_HOUSING_STARTS",
        "provider_series_id": "52300157",
        "label": "Housing starts, SAAR",
        "indicator": MacroSeries.Indicator.HOUSING,
        "parser": MacroSeries.Parser.STATCAN_ZIP,
        "frequency": "monthly",
        "unit": "thousand units",
        "url": "https://www150.statcan.gc.ca/n1/en/tbl/csv/34100158-eng.zip",
    },
    {
        "policy": "us-bls",
        "code": "US_CPI_YOY",
        "provider_series_id": "CUUR0000SA0",
        "label": "CPI inflation, all urban consumers",
        "indicator": MacroSeries.Indicator.CPI,
        "parser": MacroSeries.Parser.BLS_JSON,
        "method": "POST",
        "transform": MacroSeries.Transformation.YEAR_OVER_YEAR,
        "frequency": "monthly",
        "url": "https://api.bls.gov/publicAPI/v2/timeseries/data/",
    },
    {
        "policy": "us-bls",
        "code": "US_UNEMPLOYMENT",
        "provider_series_id": "LNS14000000",
        "label": "Unemployment rate",
        "indicator": MacroSeries.Indicator.UNEMPLOYMENT,
        "parser": MacroSeries.Parser.BLS_JSON,
        "method": "POST",
        "frequency": "monthly",
        "url": "https://api.bls.gov/publicAPI/v2/timeseries/data/",
    },
    {
        "policy": "fred",
        "code": "US_REAL_GDP_GROWTH",
        "provider_series_id": "A191RL1Q225SBEA",
        "label": "Real GDP growth",
        "indicator": MacroSeries.Indicator.GDP,
        "parser": MacroSeries.Parser.FRED_CSV,
        "frequency": "quarterly",
        "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=A191RL1Q225SBEA",
    },
    {
        "policy": "fred",
        "code": "US_HOUSING_STARTS",
        "provider_series_id": "HOUST",
        "label": "Housing starts, SAAR",
        "indicator": MacroSeries.Indicator.HOUSING,
        "parser": MacroSeries.Parser.FRED_CSV,
        "frequency": "monthly",
        "unit": "thousand units",
        "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=HOUST",
    },
    {
        "policy": "uk-ons",
        "code": "GB_CPI_YOY",
        "provider_series_id": "D7G7",
        "label": "CPI inflation",
        "indicator": MacroSeries.Indicator.CPI,
        "parser": MacroSeries.Parser.ONS_CSV,
        "frequency": "monthly",
        "url": "https://www.ons.gov.uk/generator?format=csv&uri=/economy/inflationandpriceindices/timeseries/d7g7/mm23",
    },
    {
        "policy": "uk-ons",
        "code": "GB_UNEMPLOYMENT",
        "provider_series_id": "MGSX",
        "label": "Unemployment rate",
        "indicator": MacroSeries.Indicator.UNEMPLOYMENT,
        "parser": MacroSeries.Parser.ONS_CSV,
        "frequency": "monthly",
        "url": "https://www.ons.gov.uk/generator?format=csv&uri=/employmentandlabourmarket/peoplenotinwork/unemployment/timeseries/mgsx/lms",
    },
    {
        "policy": "uk-ons",
        "code": "GB_REAL_GDP_GROWTH",
        "provider_series_id": "IHYQ",
        "label": "Real GDP growth, quarter-on-quarter",
        "indicator": MacroSeries.Indicator.GDP,
        "parser": MacroSeries.Parser.ONS_CSV,
        "frequency": "quarterly",
        "url": "https://www.ons.gov.uk/generator?format=csv&uri=/economy/grossdomesticproductgdp/timeseries/ihyq/pn2",
    },
    {
        "policy": "uk-land-registry",
        "code": "GB_HOUSE_PRICE_YOY",
        "provider_series_id": "percentage annual change",
        "label": "House price growth",
        "indicator": MacroSeries.Indicator.HOUSING,
        "parser": MacroSeries.Parser.LAND_REGISTRY_CSV,
        "frequency": "monthly",
        "url": "https://landregistry.data.gov.uk/data/ukhpi/region/united-kingdom.csv?_pageSize=120&_view=all",
    },
    {
        "policy": "eurostat",
        "code": "EU_HICP_YOY",
        "provider_series_id": "prc_hicp_minr",
        "label": "HICP inflation",
        "indicator": MacroSeries.Indicator.CPI,
        "parser": MacroSeries.Parser.EUROSTAT_JSON,
        "frequency": "monthly",
        "url": "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hicp_minr?lang=en&geo=EA21&coicop18=TOTAL&unit=RCH_A&sinceTimePeriod=2024-01",
    },
    {
        "policy": "eurostat",
        "code": "EU_UNEMPLOYMENT",
        "provider_series_id": "une_rt_m",
        "label": "Unemployment rate",
        "indicator": MacroSeries.Indicator.UNEMPLOYMENT,
        "parser": MacroSeries.Parser.EUROSTAT_JSON,
        "frequency": "monthly",
        "url": "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/une_rt_m?lang=en&geo=EA21&sex=T&age=TOTAL&s_adj=SA&unit=PC_ACT&sinceTimePeriod=2024-01",
    },
    {
        "policy": "eurostat",
        "code": "EU_REAL_GDP_GROWTH",
        "provider_series_id": "namq_10_gdp",
        "label": "Real GDP growth",
        "indicator": MacroSeries.Indicator.GDP,
        "parser": MacroSeries.Parser.EUROSTAT_JSON,
        "frequency": "quarterly",
        "url": "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/namq_10_gdp?lang=en&geo=EA21&na_item=B1GQ&s_adj=SCA&unit=CLV_PCH_PRE&sinceTimePeriod=2024-Q1",
    },
    {
        "policy": "eurostat",
        "code": "EU_HOUSE_PRICE_INDEX",
        "provider_series_id": "prc_hpi_q",
        "label": "House price index",
        "indicator": MacroSeries.Indicator.HOUSING,
        "parser": MacroSeries.Parser.EUROSTAT_JSON,
        "frequency": "quarterly",
        "unit": "index, 2015=100",
        "url": "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hpi_q?lang=en&geo=EA21&purchase=TOTAL&unit=I15_Q&sinceTimePeriod=2024-Q1",
    },
    {
        "policy": "fred",
        "code": "GLOBAL_SP500",
        "provider_series_id": "SP500",
        "label": "S&P 500 index",
        "indicator": MacroSeries.Indicator.EQUITY,
        "parser": MacroSeries.Parser.FRED_CSV,
        "frequency": "business daily",
        "unit": "index",
        "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500",
    },
    {
        "policy": "fred",
        "code": "GLOBAL_VIX",
        "provider_series_id": "VIXCLS",
        "label": "CBOE volatility index",
        "indicator": MacroSeries.Indicator.VOLATILITY,
        "parser": MacroSeries.Parser.FRED_CSV,
        "frequency": "business daily",
        "unit": "index",
        "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS",
    },
    {
        "policy": "fred",
        "code": "GLOBAL_BITCOIN_USD",
        "provider_series_id": "CBBTCUSD",
        "label": "Bitcoin price in US dollars",
        "indicator": MacroSeries.Indicator.CRYPTO,
        "parser": MacroSeries.Parser.FRED_CSV,
        "frequency": "daily",
        "unit": "USD per bitcoin",
        "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CBBTCUSD",
    },
    {
        "policy": "fred",
        "code": "GLOBAL_WTI_USD",
        "provider_series_id": "DCOILWTICO",
        "label": "WTI crude oil spot price",
        "indicator": MacroSeries.Indicator.COMMODITY,
        "parser": MacroSeries.Parser.FRED_CSV,
        "frequency": "business daily",
        "unit": "USD per barrel",
        "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILWTICO",
    },
    {
        "policy": "fred",
        "code": "US_TREASURY_10Y",
        "provider_series_id": "DGS10",
        "label": "US Treasury 10-year yield",
        "indicator": MacroSeries.Indicator.YIELD,
        "parser": MacroSeries.Parser.FRED_CSV,
        "frequency": "business daily",
        "unit": "percent",
        "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10",
    },
    {
        "policy": "fred",
        "code": "GLOBAL_BROAD_USD",
        "provider_series_id": "DTWEXBGS",
        "label": "Nominal broad US dollar index",
        "indicator": MacroSeries.Indicator.DOLLAR,
        "parser": MacroSeries.Parser.FRED_CSV,
        "frequency": "business daily",
        "unit": "index, Jan 2006=100",
        "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTWEXBGS",
    },
    {
        "policy": "world-bank-gold-datahub",
        "code": "GLOBAL_GOLD_USD",
        "provider_series_id": "Price",
        "label": "Gold price",
        "indicator": MacroSeries.Indicator.COMMODITY,
        "parser": MacroSeries.Parser.DATE_VALUE_CSV,
        "frequency": "monthly",
        "unit": "USD per troy ounce",
        "url": "https://datahub.io/core/gold-prices/_r/-/data/monthly-processed.csv",
    },
)

CALENDARS = (
    {
        "policy": "statistics-canada",
        "parser": "statcan",
        "label": "Statistics Canada key indicators",
        "url": "https://www150.statcan.gc.ca/n1/dai-quo/ssi/homepage/schedule-key_indicators-eng.json",
    },
    {
        "policy": "us-bea",
        "parser": "bea",
        "label": "BEA release dates",
        "url": "https://apps.bea.gov/API/signup/release_dates.json",
    },
    {
        "policy": "uk-ons",
        "parser": "ons",
        "label": "ONS upcoming releases",
        "url": "https://www.ons.gov.uk/releasecalendar?rss&limit=100&release-type=type-upcoming&sort=date-newest",
    },
    {
        "policy": "eurostat",
        "parser": "eurostat",
        "label": "Eurostat euro indicators",
        "url": "https://ec.europa.eu/eurostat/o/calendars/eventsIcal?theme=2&category=2",
    },
    {
        "policy": "bank-of-canada",
        "parser": "boc",
        "label": "Bank of Canada policy decisions",
        "url": "https://www.bankofcanada.ca/feed/?content_type=upcoming-events&post_type%5B0%5D=post",
    },
    {
        "policy": "federal-reserve",
        "parser": "fed",
        "label": "Federal Reserve policy decisions",
        "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
    },
    {
        "policy": "bank-of-england",
        "parser": "boe",
        "label": "Bank of England policy decisions",
        "url": "https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates",
    },
    {
        "policy": "european-central-bank",
        "parser": "ecb",
        "label": "ECB policy decisions",
        "url": "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html",
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
                    "tier": item.get("tier", SourceRegistry.Tier.PRIMARY),
                    "base_url": item["base_url"],
                    "terms_url": item["terms_url"],
                    "acquisition_method": item.get("acquisition_method", "Official HTTPS API/RSS"),
                    "retention_policy": item.get(
                        "retention_policy",
                        "Bounded immutable official-source snapshots; private research only.",
                    ),
                    "llm_processing_allowed": item.get("llm_processing_allowed", False),
                    "attribution_required": True,
                    "deletion_policy": "Remove if official terms or owner policy requires deletion.",
                    "export_policy": "No redistribution of raw source bodies.",
                    "enabled": not item.get("commercial") or bool(settings.EODHD_API_TOKEN),
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
                    "retention_class": (
                        "commercial-private-trial"
                        if item.get("commercial")
                        else "official-public-record"
                    ),
                    "full_text_allowed": False,
                    "state": (
                        SourcePolicy.State.ENABLED
                        if not item.get("commercial") or settings.EODHD_API_TOKEN
                        else SourcePolicy.State.DISABLED
                    ),
                    "quality_note": (
                        "Commercial calendar adapter verified; API key required before collection."
                        if item.get("commercial")
                        else "Allowlisted endpoint verified; article full text is not collected."
                    ),
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
                    "indicator": item.get("indicator", MacroSeries.Indicator.POLICY_RATE),
                    "unit": item.get("unit", "percent"),
                    "frequency": item.get("frequency", "business daily"),
                    "parser": item["parser"],
                    "url": item["url"],
                    "request_method": item.get("method", MacroSeries.RequestMethod.GET),
                    "request_payload": item.get("payload", {}),
                    "transformation": item.get("transform", MacroSeries.Transformation.NONE),
                    "enabled": True,
                    "point_in_time_note": (
                        "Provider release timestamp is retained when supplied; otherwise availability is conservatively the first retrieval time. Revisions are captured prospectively."
                    ),
                },
            )
            _upsert_job(
                f"Research macro — {series.code}",
                "research.ingest_macro",
                {"series": series.code},
                86_400,
            )
        ScheduledJob.objects.filter(task_name="research.ingest_macro").exclude(
            name__in=[f"Research macro — {item['code']}" for item in SERIES]
        ).delete()
        for item in CALENDARS:
            _upsert_job(
                f"Research calendar — {item['label']}",
                "research.ingest_official_calendar",
                {
                    "source": item["policy"],
                    "parser": item["parser"],
                    "url": item["url"],
                },
                86_400,
            )
        ScheduledJob.objects.filter(task_name="research.ingest_official_calendar").exclude(
            name__in=[f"Research calendar — {item['label']}" for item in CALENDARS]
        ).delete()
        _upsert_job(
            "Research evidence — all active pairs",
            "research.capture_pair_evidence",
            {},
            14_400,
        )
        _upsert_job(
            "Forecast recommendations — all active pairs",
            "forecast.generate_recommendations",
            {},
            14_400,
            enabled=(settings.RECOMMENDATION_SCHEDULE_ENABLED and bool(settings.ANTHROPIC_API_KEY)),
        )
        _upsert_job(
            "Forecast postmortems — bounded interpretation",
            "forecast.interpret_postmortems",
            {},
            86_400,
            enabled=(
                settings.POSTMORTEM_INTERPRETATION_ENABLED and bool(settings.ANTHROPIC_API_KEY)
            ),
        )
        _upsert_job(
            "Forecast experiments — dependence-aware health",
            "forecast.refresh_experiment_health",
            {},
            86_400,
        )
        from forecasts.experiments import ensure_champion_era
        from forecasts.recommendations import configured_provider

        ensure_champion_era(configured_provider())
        ProviderEvaluation.objects.update_or_create(
            category="economic-calendar",
            provider="Official statistical agencies",
            defaults={
                "status": ProviderEvaluation.Status.SELECTED,
                "evidence_url": "https://ec.europa.eu/eurostat/news/release-calendar",
                "pricing_status": "Free official public schedules",
                "timestamp_semantics": "Exact official times where supplied; Eurostat date-only events remain date-only",
                "revision_support": "Every retrieval and changed normalized schedule payload is retained prospectively",
                "retention_rights": "Official public records retained for private research; no raw-body redistribution",
                "reliability_result": "SELECTED — EIGHT OFFICIAL STATISTICAL AND POLICY SCHEDULES",
                "next_check": "Add BLS and Census schedules only when their official endpoints are reliably automatable.",
            },
        )
        ProviderEvaluation.objects.update_or_create(
            category="economic-calendar",
            provider="EODHD",
            defaults={
                "status": ProviderEvaluation.Status.REJECTED,
                "evidence_url": "https://eodhd.com/financial-apis/economic-events-data-api",
                "pricing_status": (
                    "USD $59.99 monthly or $599.90 annually ($49.99/month equivalent); key configured"
                    if settings.EODHD_API_TOKEN
                    else "USD $59.99 monthly or $599.90 annually ($49.99/month equivalent); key not configured"
                ),
                "timestamp_semantics": "Event date/time plus actual, estimate, and previous; timezone semantics require trial verification",
                "revision_support": "Distinct changed payloads are retained prospectively; provider vintage guarantees not documented",
                "retention_rights": "Private-use terms reviewed at a high level; confirm model-input and long-term retention rights before purchase",
                "reliability_result": "NOT SELECTED — FREE KEY EXCLUDES ECONOMIC EVENTS",
                "next_check": "Optional future source for consensus only; no purchase is needed for release schedules.",
            },
        )
        ProviderEvaluation.objects.update_or_create(
            category="economic-calendar",
            provider="Trading Economics",
            defaults={
                "status": ProviderEvaluation.Status.CANDIDATE,
                "evidence_url": "https://docs.tradingeconomics.com/",
                "pricing_status": "No public price verified within budget",
                "timestamp_semantics": "To be measured against official release timestamps",
                "revision_support": "To be tested during a bounded trial",
                "retention_rights": "Terms and API retention rights require review",
                "reliability_result": "NOT SELECTED — QUOTE/RIGHTS REQUIRED",
                "next_check": "Request a quote and written retention/model-input rights before considering a trial.",
            },
        )
        _upsert_job(
            "Research calendar — EODHD",
            "research.ingest_eodhd_calendar",
            {},
            3_600,
            enabled=False,
        )
        self.stdout.write(self.style.SUCCESS("official research registry ready"))


def _upsert_job(name, task_name, parameters, interval, *, enabled=True):
    job, _ = ScheduledJob.objects.get_or_create(
        name=name,
        defaults={
            "task_name": task_name,
            "parameters": parameters,
            "interval_seconds": interval,
            "next_run_at": timezone.now() + timedelta(seconds=interval),
            "enabled": enabled,
        },
    )
    job.task_name = task_name
    job.parameters = parameters
    job.interval_seconds = interval
    job.enabled = enabled
    job.save(update_fields=("task_name", "parameters", "interval_seconds", "enabled"))
