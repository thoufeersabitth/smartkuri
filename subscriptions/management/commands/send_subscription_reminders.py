from django.core.management.base import BaseCommand
from subscriptions.notifications import check_and_send_subscription_reminders


class Command(BaseCommand):
    help = "Checks subscription expiration and dispatches FCM push notifications for 2 days left, 1 day left, and expired status."

    def handle(self, *args, **kwargs):
        self.stdout.write("Checking subscription expiration reminders...")
        count = check_and_send_subscription_reminders()
        self.stdout.write(
            self.style.SUCCESS(f"Successfully sent {count} subscription reminder notification(s).")
        )
