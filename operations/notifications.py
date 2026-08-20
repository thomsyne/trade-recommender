from django.conf import settings
from django.core.exceptions import ValidationError

from operations.models import OwnerNotification
from operations.services import enqueue_outbox


def create_owner_notification(
    *,
    idempotency_key,
    kind,
    severity,
    title,
    body,
    action_path,
    subject_type,
    subject_id,
):
    if action_path and (not action_path.startswith("/") or action_path.startswith("//")):
        raise ValidationError("Notification action must be a safe internal path")
    notification, created = OwnerNotification.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={
            "kind": kind,
            "severity": severity,
            "title": title,
            "body": body,
            "action_path": action_path,
            "subject_type": subject_type,
            "subject_id": subject_id,
        },
    )
    if created and settings.EMAIL_DELIVERY_ENABLED:
        enqueue_outbox(
            idempotency_key=f"owner-email:{notification.pk}",
            channel="email",
            template="owner_notification",
            payload={"notification_id": notification.pk},
        )
    return notification
