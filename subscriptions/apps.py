import os
import threading
import time
from django.apps import AppConfig


class SubscriptionsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'subscriptions'

    def ready(self):
        # Auto-run subscription reminder scheduler in background daemon
        if os.environ.get('RUN_MAIN') == 'true':
            def _scheduler_loop():
                time.sleep(15)  # brief wait for DB/server to become ready
                while True:
                    try:
                        from subscriptions.notifications import check_and_send_subscription_reminders
                        check_and_send_subscription_reminders()
                    except Exception:
                        pass
                    time.sleep(3600)  # check hourly (deduplicated per day)

            t = threading.Thread(target=_scheduler_loop, daemon=True, name="SubscriptionReminderDaemon")
            t.start()

