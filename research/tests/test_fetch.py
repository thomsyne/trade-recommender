import gzip

import httpx
from django.test import TestCase

from research.fetch import FetchRejected, fetch, validate_url
from research.tests.factories import source_policy

PUBLIC_RESOLVER = lambda _host: {"93.184.216.34"}  # noqa: E731


class SafeFetchTests(TestCase):
    def setUp(self):
        self.policy = source_policy()

    def test_rejects_non_https_credentials_wrong_hosts_and_private_dns(self):
        cases = (
            "http://official.example/feed",
            "https://user:password@official.example/feed",
            "https://unapproved.example/feed",
        )
        for url in cases:
            with self.subTest(url=url), self.assertRaises(FetchRejected):
                validate_url(url, self.policy, PUBLIC_RESOLVER)
        with self.assertRaisesRegex(FetchRejected, "non-public"):
            validate_url("https://official.example/feed", self.policy, lambda _host: {"127.0.0.1"})

    def test_revalidates_redirect_destination(self):
        self.policy.allowed_hosts = ["official.example", "redirect.example"]

        def handler(request):
            return httpx.Response(302, headers={"location": "https://redirect.example/private"})

        def resolver(host):
            return {"127.0.0.1"} if host == "redirect.example" else {"93.184.216.34"}

        with self.assertRaisesRegex(FetchRejected, "non-public"):
            fetch(
                self.policy,
                "https://official.example/feed",
                transport=httpx.MockTransport(handler),
                resolver=resolver,
            )

    def test_rejects_private_connected_peer_after_public_dns_check(self):
        class PrivateStream:
            def get_extra_info(self, _key):
                return ("10.0.0.8", 443)

        transport = httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"content-type": "application/rss+xml"},
                content=b"<rss />",
                extensions={"network_stream": PrivateStream()},
            )
        )
        with self.assertRaisesRegex(FetchRejected, "connected source address is non-public"):
            fetch(
                self.policy,
                "https://official.example/feed",
                transport=transport,
                resolver=PUBLIC_RESOLVER,
            )

    def test_rejects_wrong_content_type_and_oversized_decoded_body(self):
        for headers, body, reason in (
            ({"content-type": "text/html"}, b"okay", "content type"),
            ({"content-type": "application/rss+xml"}, b"x" * 10_001, "response size"),
        ):
            transport = httpx.MockTransport(
                lambda _request: httpx.Response(200, headers=headers, content=body)
            )
            with self.subTest(reason=reason), self.assertRaisesRegex(FetchRejected, reason):
                fetch(
                    self.policy,
                    "https://official.example/feed",
                    transport=transport,
                    resolver=PUBLIC_RESOLVER,
                )

    def test_accepts_bounded_allowed_response(self):
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"content-type": "application/rss+xml; charset=utf-8"},
                content=b"<rss />",
            )
        )
        result = fetch(
            self.policy,
            "https://official.example/feed",
            transport=transport,
            resolver=PUBLIC_RESOLVER,
        )
        self.assertEqual(result.body, b"<rss />")
        self.assertEqual(result.content_type, "application/rss+xml")

    def test_post_body_is_sent_and_sensitive_query_is_not_persisted(self):
        seen = {}

        def handler(request):
            seen["method"] = request.method
            seen["body"] = request.content
            return httpx.Response(
                200, headers={"content-type": "application/rss+xml"}, content=b"[]"
            )

        result = fetch(
            self.policy,
            "https://official.example/feed?api_token=secret",
            method="POST",
            json_body={"vectorId": 123},
            sensitive_query_keys=("api_token",),
            transport=httpx.MockTransport(handler),
            resolver=PUBLIC_RESOLVER,
        )
        self.assertEqual(seen["method"], "POST")
        self.assertIn(b'"vectorId":123', seen["body"])
        self.assertNotIn("secret", result.url)
        self.assertNotIn("secret", result.request_fingerprint)

    def test_rejects_small_compressed_payload_that_expands_over_limit(self):
        compressed = gzip.compress(b"x" * 10_001)
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={
                    "content-type": "application/rss+xml",
                    "content-encoding": "gzip",
                },
                stream=httpx.ByteStream(compressed),
            )
        )
        with self.assertRaisesRegex(FetchRejected, "decoded response size"):
            fetch(
                self.policy,
                "https://official.example/feed",
                transport=transport,
                resolver=PUBLIC_RESOLVER,
            )
