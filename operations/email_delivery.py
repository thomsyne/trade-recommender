import smtplib
from urllib.parse import urljoin

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from operations.models import DeliveryAttempt, OwnerNotification
from operations.services import claim_outbox, finish_outbox


def deliver_one_email(worker_id):
    if not settings.EMAIL_DELIVERY_ENABLED:
        return False
    message = claim_outbox(worker_id)
    if not message:
        return False
    try:
        if message.channel != "email" or message.template != "owner_notification":
            raise ValueError("Unsupported outbox delivery contract")
        notification = OwnerNotification.objects.get(pk=message.payload["notification_id"])
        action_url = (
            urljoin(f"{settings.PUBLIC_URL}/", notification.action_path.lstrip("/"))
            if notification.action_path
            else settings.PUBLIC_URL
        )
        context = {"notification": notification, "action_url": action_url}
        email = EmailMultiAlternatives(
            subject=f"FX Forecast Lab — {notification.title}",
            body=render_to_string("email/owner_notification.txt", context),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[settings.OWNER_EMAIL],
        )
        email.attach_alternative(
            render_to_string("email/owner_notification.html", context), "text/html"
        )
        sent = email.send(fail_silently=False)
        if sent != 1:
            raise RuntimeError("Email backend did not confirm one delivery")
    except smtplib.SMTPServerDisconnected:
        finish_outbox(
            message,
            worker_id,
            DeliveryAttempt.Outcome.UNCERTAIN,
            error_code="smtp_disconnected",
            summary="SMTP connection closed before delivery outcome was confirmed",
        )
    except (smtplib.SMTPException, ValueError, KeyError, OwnerNotification.DoesNotExist):
        finish_outbox(
            message,
            worker_id,
            DeliveryAttempt.Outcome.FAILED,
            error_code="email_delivery_failed",
            summary="Email delivery failed",
        )
    except Exception:
        finish_outbox(
            message,
            worker_id,
            DeliveryAttempt.Outcome.UNCERTAIN,
            error_code="email_outcome_uncertain",
            summary="Email delivery outcome is uncertain",
        )
    else:
        finish_outbox(message, worker_id, DeliveryAttempt.Outcome.SUCCEEDED)
    return True
