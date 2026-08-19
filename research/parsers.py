import csv
import io
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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
    text = body.decode("utf-8-sig")
    if series.parser == MacroSeries.Parser.BOC_VALET:
        payload = json.loads(text)
        rows = [
            (row.get("d"), (row.get(series.provider_series_id) or {}).get("v"))
            for row in payload.get("observations", [])
        ]
    else:
        records = list(csv.DictReader(io.StringIO(text)))
        if series.parser == MacroSeries.Parser.FRED_CSV:
            rows = [
                (row.get("observation_date"), row.get(series.provider_series_id)) for row in records
            ]
        elif series.parser == MacroSeries.Parser.ECB_CSV:
            rows = [(row.get("TIME_PERIOD"), row.get("OBS_VALUE")) for row in records]
        elif series.parser == MacroSeries.Parser.BOE_CSV:
            rows = [(row.get("DATE"), row.get(series.provider_series_id)) for row in records]
        else:
            raise ParseRejected(f"unsupported macro parser: {series.parser}")
    values = []
    for raw_period, raw_value in rows[-400:]:
        if not raw_period or raw_value in {None, "", "."}:
            continue
        try:
            value = Decimal(str(raw_value))
            period = _parse_date(raw_period)
        except (InvalidOperation, ValueError) as error:
            raise ParseRejected("macro response contains an invalid observation") from error
        values.append(MacroValue(period, value, format(value.normalize(), "f")))
    if not values:
        raise ParseRejected("macro response contains no usable observations")
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
    for pattern in ("%Y-%m-%d", "%d %b %Y", "%Y-%m"):
        try:
            parsed = datetime.strptime(value.strip(), pattern).date()
            return parsed.replace(day=1) if pattern == "%Y-%m" else parsed
        except ValueError:
            continue
    raise ValueError(f"unsupported observation date: {value}")
