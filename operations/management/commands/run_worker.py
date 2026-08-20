import os
import socket
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError

from django.core.management.base import BaseCommand

from operations.email_delivery import deliver_one_email
from operations.services import claim_next_job, finish_job, heartbeat_job
from operations.tasks import execute_task


class Command(BaseCommand):
    help = "Run the durable database-backed worker"

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex}"
        with ThreadPoolExecutor(max_workers=1) as executor:
            while True:
                occurrence = claim_next_job(worker_id)
                if occurrence:
                    future = executor.submit(
                        execute_task, occurrence.task_name, occurrence.parameters
                    )
                    while True:
                        try:
                            future.result(timeout=60)
                        except TimeoutError:
                            if not heartbeat_job(occurrence, worker_id):
                                self.stderr.write(f"job {occurrence.pk} exceeded its lease")
                                break
                        except Exception as error:
                            finish_job(occurrence, worker_id, error=error)
                            self.stderr.write(f"job {occurrence.pk} failed")
                            break
                        else:
                            finish_job(occurrence, worker_id)
                            break
                email_delivered = deliver_one_email(worker_id)
                if options["once"]:
                    return
                if not occurrence and not email_delivered:
                    time.sleep(5)
