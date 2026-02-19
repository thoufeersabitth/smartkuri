from django.core.management.base import BaseCommand
from subscriptions.services import close_expired_subscriptions


class Command(BaseCommand):
    help = "Close expired subscriptions automatically"

    def handle(self, *args, **kwargs):
        count = close_expired_subscriptions()
        self.stdout.write(
            self.style.SUCCESS(f"{count} subscriptions closed.")
        )
