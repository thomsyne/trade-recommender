import csv
import io
import json
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from defusedxml import ElementTree

from research.models import MacroSeries


class ParseRejected(ValueError):
    pass


@dataclass(frozen=True)
class FeedItem:
    item_id: str
    url: str
    title: str
    published_at: datetime | None
    summary: str


@dataclass(frozen=True)
class MacroValue:
    period: object
    value: Decimal
    normalized_value: str
    available_at: datetime | None = None
    provider_status: str = ""


@dataclass(frozen=True)
class CalendarValue:
    event_at: datetime
    country: str
    event_type: str
    comparison: str
    period: str
    actual: Decimal | None
    estimate: Decimal | None
    previous: Decimal | None


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain_text(value):
    parser = _TextExtractor()
    parser.feed(value or "")
    return " ".join(" ".join(parser.parts).split())


def canonicalize_url(value):
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ParseRejected("feed item has no valid canonical URL")
    query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}
    ]
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", urlencode(query), "")
    )


def parse_feed(body):
    try:
        root = ElementTree.fromstring(body)
    except Exception as error:
        raise ParseRejected(f"unsafe or invalid XML: {error}") from error
    nodes = [node for node in root.iter() if _local(node.tag) in {"item", "entry"}]
    if not nodes:
        raise ParseRejected("RSS/Atom document contains no items")
    items = []
    for node in nodes:
        title = plain_text(_child_text(node, "title"))
        url = _link(node)
        item_id = _child_text(node, "guid", "id") or url
        published_raw = _child_text(node, "pubDate", "published", "updated", "date")
        summary = plain_text(_child_text(node, "description", "summary", "content", "encoded"))[
            :20_000
        ]
        if not title or not url:
            continue
        items.append(
            FeedItem(
                item_id=item_id.strip(),
                url=canonicalize_url(url),
                title=title[:2000],
                published_at=_parse_datetime(published_raw),
                summary=summary,
            )
        )
    if not items:
        raise ParseRejected("RSS/Atom document contains no usable items")
    return items


def parse_macro(series, body):
    if series.parser == MacroSeries.Parser.STATCAN_ZIP:
        text = _bounded_zip_csv(body)
    else:
        text = body.decode("utf-8-sig")
    if series.parser == MacroSeries.Parser.BOC_VALET:
        payload = json.loads(text)
        rows = [
            (row.get("d"), (row.get(series.provider_series_id) or {}).get("v"))
            for row in payload.get("observations", [])
        ]
        rows = [(period, value, None, "") for period, value in rows]
    elif series.parser == MacroSeries.Parser.STATCAN_WDS:
        payload = json.loads(text)
        match = next(
            (
                item.get("object", {})
                for item in payload
                if str(item.get("object", {}).get("vectorId")) == series.provider_series_id
            ),
            None,
        )
        if not match:
            raise ParseRejected("Statistics Canada response does not contain the requested vector")
        rows = [
            (
                row.get("refPer"),
                row.get("value"),
                _statcan_release_time(row.get("releaseTime")),
                f"status={row.get('statusCode', 0)}; symbol={row.get('symbolCode', 0)}",
            )
            for row in match.get("vectorDataPoint", [])
        ]
    elif series.parser == MacroSeries.Parser.BLS_JSON:
        payload = json.loads(text)
        if payload.get("status") != "REQUEST_SUCCEEDED":
            raise ParseRejected("BLS request did not succeed")
        match = next(
            (
                item
                for item in payload.get("Results", {}).get("series", [])
                if item.get("seriesID") == series.provider_series_id
            ),
            None,
        )
        if not match:
            raise ParseRejected("BLS response does not contain the requested series")
        rows = [
            (
                f"{row.get('year')}-{row.get('period', '')[1:]}",
                row.get("value"),
                None,
                "; ".join(note.get("text", "") for note in row.get("footnotes", []) if note),
            )
            for row in match.get("data", [])
            if row.get("period") != "M13"
        ]
    elif series.parser == MacroSeries.Parser.EUROSTAT_JSON:
        payload = json.loads(text)
        time_index = (
            payload.get("dimension", {}).get("time", {}).get("category", {}).get("index", {})
        )
        positions = (
            time_index.items()
            if isinstance(time_index, dict)
            else ((period, index) for index, period in enumerate(time_index))
        )
        values = payload.get("value", {})
        statuses = payload.get("status", {})
        available = _parse_datetime(payload.get("updated"))
        rows = [
            (
                period,
                values.get(str(index)) if isinstance(values, dict) else values[index],
                available,
                str(statuses.get(str(index), "") if isinstance(statuses, dict) else ""),
            )
            for period, index in positions
            if (str(index) in values if isinstance(values, dict) else index < len(values))
        ]
    else:
        records = list(csv.DictReader(io.StringIO(text)))
        if series.parser == MacroSeries.Parser.FRED_CSV:
            rows = [
                (row.get("observation_date"), row.get(series.provider_series_id), None, "")
                for row in records
            ]
        elif series.parser == MacroSeries.Parser.ECB_CSV:
            rows = [(row.get("TIME_PERIOD"), row.get("OBS_VALUE"), None, "") for row in records]
        elif series.parser == MacroSeries.Parser.BOE_CSV:
            rows = [
                (row.get("DATE"), row.get(series.provider_series_id), None, "") for row in records
            ]
        elif series.parser == MacroSeries.Parser.ONS_CSV:
            rows = [
                (row[0], row[1], None, "")
                for row in csv.reader(io.StringIO(text))
                if len(row) >= 2 and _looks_like_period(row[0])
            ]
        elif series.parser == MacroSeries.Parser.LAND_REGISTRY_CSV:
            rows = [
                (row.get("ref period start"), row.get(series.provider_series_id), None, "")
                for row in records
            ]
        elif series.parser == MacroSeries.Parser.STATCAN_ZIP:
            rows = [
                (row.get("REF_DATE"), row.get("VALUE"), None, row.get("STATUS", ""))
                for row in records
                if row.get("VECTOR", "").lstrip("v") == series.provider_series_id
            ]
        else:
            raise ParseRejected(f"unsupported macro parser: {series.parser}")
    values = []
    for raw_period, raw_value, available_at, provider_status in rows[-400:]:
        if not raw_period or raw_value in {None, "", ".", "-", "NA", ":"}:
            continue
        try:
            value = Decimal(str(raw_value))
            period = _parse_date(raw_period)
        except (InvalidOperation, ValueError) as error:
            raise ParseRejected("macro response contains an invalid observation") from error
        values.append(
            MacroValue(
                period,
                value,
                format(value.normalize(), "f"),
                available_at,
                provider_status[:80],
            )
        )
    if not values:
        raise ParseRejected("macro response contains no usable observations")
    if series.transformation == MacroSeries.Transformation.YEAR_OVER_YEAR:
        by_period = {item.period: item for item in values}
        transformed = []
        for item in values:
            prior = by_period.get(_year_before(item.period))
            if prior and prior.value:
                value = (item.value / prior.value - 1) * Decimal("100")
                transformed.append(
                    MacroValue(
                        item.period,
                        value,
                        format(value.normalize(), "f"),
                        item.available_at,
                        item.provider_status,
                    )
                )
        values = transformed
    if not values:
        raise ParseRejected("macro transformation contains no usable observations")
    return values


def parse_eodhd_events(body):
    payload = json.loads(body.decode("utf-8-sig"))
    if not isinstance(payload, list):
        raise ParseRejected("economic calendar response is not a list")
    values = []
    for row in payload:
        try:
            event_at = datetime.strptime(row["date"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
            country = str(row["country"]).upper()
            event_type = str(row["type"]).strip()
        except (KeyError, TypeError, ValueError) as error:
            raise ParseRejected("economic calendar response contains an invalid event") from error
        if len(country) != 2 or not event_type:
            raise ParseRejected("economic calendar response contains an invalid event identity")
        values.append(
            CalendarValue(
                event_at,
                country,
                event_type,
                str(row.get("comparison") or "")[:12],
                str(row.get("period") or "")[:40],
                _optional_decimal(row.get("actual")),
                _optional_decimal(row.get("estimate")),
                _optional_decimal(row.get("previous")),
            )
        )
    return values


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _child_text(node, *names):
    for child in node:
        if _local(child.tag) in names and child.text:
            return child.text
    return ""


def _link(node):
    for child in node:
        if _local(child.tag) == "link":
            return child.attrib.get("href") or (child.text or "")
    return ""


def _parse_datetime(value):
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_date(value):
    value = value.strip()
    for pattern in ("%Y-%m-%d", "%d %b %Y", "%Y-%m", "%Y %b"):
        try:
            parsed = datetime.strptime(value.strip(), pattern).date()
            return parsed.replace(day=1) if pattern == "%Y-%m" else parsed
        except ValueError:
            continue
    if len(value) == 7 and value[4:6] in {" Q", "-Q"} and value[-1] in "1234":
        return datetime(int(value[:4]), (int(value[-1]) - 1) * 3 + 1, 1).date()
    raise ValueError(f"unsupported observation date: {value}")


def _looks_like_period(value):
    try:
        _parse_date(value)
        return True
    except ValueError:
        return False


def _statcan_release_time(value):
    if not value:
        return None
    parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M")
    return parsed.replace(tzinfo=ZoneInfo("America/Toronto")).astimezone(UTC)


def _year_before(value):
    try:
        return value.replace(year=value.year - 1)
    except ValueError:
        return value.replace(year=value.year - 1, day=28)


def _optional_decimal(value):
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation as error:
        raise ParseRejected("economic calendar response contains an invalid number") from error


def _bounded_zip_csv(body):
    try:
        archive = zipfile.ZipFile(io.BytesIO(body))
        names = [
            item
            for item in archive.infolist()
            if item.filename.lower().endswith(".csv") and "metadata" not in item.filename.lower()
        ]
        if len(names) != 1 or names[0].file_size > 2_000_000:
            raise ParseRejected("Statistics Canada archive is not a bounded single-table CSV")
        return archive.read(names[0]).decode("utf-8-sig")
    except (zipfile.BadZipFile, UnicodeDecodeError) as error:
        raise ParseRejected("Statistics Canada archive is invalid") from error
