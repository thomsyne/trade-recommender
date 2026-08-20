# Gmail owner notifications

FX Forecast Lab can send its controlled owner notifications through Gmail SMTP.
The dashboard inbox remains the system of record, and portfolio decisions can
only be submitted inside the authenticated application. Email links are normal
dashboard links, not approval tokens.

Delivery is disabled by default. Configure these deployment secrets/settings:

```text
EMAIL_DELIVERY_ENABLED=true
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=465
EMAIL_USE_SSL=true
EMAIL_USE_TLS=false
EMAIL_HOST_USER=sender@gmail.com
EMAIL_HOST_PASSWORD=<Google app password>
DEFAULT_FROM_EMAIL=sender@gmail.com
OWNER_EMAIL=recipient@gmail.com
PUBLIC_URL=https://your-private-dashboard.example
```

Use a Google app password, never the normal Gmail account password. The sender
account must have two-step verification enabled before Google exposes app
passwords. Store all values in the deployment secret manager; do not commit
them to Git.

The worker renders allowlisted Django templates with both plain-text and HTML
parts. It does not accept raw HTML from recommendation or news payloads.
Logical messages are idempotent, attempts are retained, transient failures use
bounded outbox retries, and an SMTP disconnect after an attempted send is
recorded as uncertain rather than blindly duplicated.

For local verification, use Django's in-memory email backend in tests. Do not
enable real delivery until `PUBLIC_URL` is the canonical authenticated origin
and a test message has been reviewed for recipient, links, and redaction.
