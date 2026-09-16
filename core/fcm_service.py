import logging
import firebase_admin
from firebase_admin import messaging
from accounts.models import FCMDeviceToken

logger = logging.getLogger(__name__)

# Initialize Firebase app if not already initialized
if not firebase_admin._apps:
    try:
        firebase_admin.initialize_app()
    except Exception as e:
        logger.warning(f"Firebase default app initialization: {e}")


def send_push_to_user(user, title, body, data=None):
    """
    Sends an FCM push notification to all active devices registered to a User.
    """
    if not user:
        return 0

    tokens = list(
        FCMDeviceToken.objects.filter(user=user).values_list('token', flat=True)
    )
    if not tokens:
        logger.info(f"No FCM device tokens found for user {user.username}")
        return 0

    success_count = 0
    clean_data = {str(k): str(v) for k, v in (data or {}).items()}

    # Android specific config for WhatsApp-style High Priority heads up banner
    android_config = messaging.AndroidConfig(
        priority='high',
        notification=messaging.AndroidNotification(
            channel_id='smartkuri_alerts_channel',
            sound='default',
            priority='max',
            default_sound=True,
            default_vibrate_timings=True,
            visibility='public',
        )
    )

    for token in tokens:
        try:
            message = messaging.Message(
                notification=messaging.Notification(
                    title=title,
                    body=body,
                ),
                data=clean_data,
                token=token,
                android=android_config,
            )
            response = messaging.send(message)
            logger.info(f"Successfully sent FCM push to {user.username}: {response}")
            success_count += 1
        except Exception as e:
            err_str = str(e)
            logger.error(f"Failed to send FCM to token {token[:15]}...: {err_str}")
            # Clean up invalid or unregistered tokens
            if "registration-token-not-registered" in err_str or "invalid-registration-token" in err_str:
                FCMDeviceToken.objects.filter(token=token).delete()

    return success_count


def send_push_to_users(users, title, body, data=None):
    """
    Broadcasts FCM push notification to a collection of users.
    """
    total = 0
    for u in users:
        total += send_push_to_user(u, title, body, data)
    return total
