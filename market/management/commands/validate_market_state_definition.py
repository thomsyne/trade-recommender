"""Validate a bounded definition envelope without querying or registering it."""

import json

from django.core.management.base import BaseCommand, CommandError

from market.state.canonical import identity_digest
from market.state.compute import DESCRIPTOR_KEY, DESCRIPTOR_VERSION
from market.state.definitions import validate_definition_body

MAX_BYTES = 65536


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


class Command(BaseCommand):
    requires_system_checks = []
    help = (
        "Validate JSON envelope {key, version, definition, definition_sha256}; max 64 KiB; no DB."
    )

    def add_arguments(self, parser):
        parser.add_argument("path")

    def handle(self, *args, **options):
        try:
            with open(options["path"], "rb") as source:
                data = source.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError
            envelope = json.loads(data, object_pairs_hook=unique_object)
            if not isinstance(envelope, dict) or set(envelope) != {
                "key",
                "version",
                "definition",
                "definition_sha256",
            }:
                raise ValueError
            if (envelope["key"], envelope["version"]) != (DESCRIPTOR_KEY, DESCRIPTOR_VERSION):
                raise ValueError
            validate_definition_body(envelope["definition"])
            digest = identity_digest(envelope["definition"])
            if envelope["definition_sha256"] != digest:
                raise ValueError
        except (OSError, ValueError, TypeError, RecursionError):
            raise CommandError("invalid_definition") from None
        self.stdout.write(json.dumps({"valid": True, "definition_sha256": digest}, sort_keys=True))
