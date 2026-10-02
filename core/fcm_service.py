import os
import glob
import logging
from pathlib import Path
from django.conf import settings
import firebase_admin
from firebase_admin import credentials, messaging
from accounts.models import FCMDeviceToken

logger = logging.getLogger(__name__)


def get_firebase_app():
    """
    Ensures Firebase Admin is initialized with valid service account credentials.
    Checks GOOGLE_APPLICATION_CREDENTIALS, settings.FIREBASE_CREDENTIALS,
    and looks for 'firebase-service-account.json' or '*firebase-adminsdk*.json' in BASE_DIR.
    """
    if firebase_admin._apps:
        try:
            return firebase_admin.get_app()
        except Exception:
            pass

    cred_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')

    if not cred_path and hasattr(settings, 'FIREBASE_CREDENTIALS'):
        cred_path = settings.FIREBASE_CREDENTIALS

    if not cred_path or not os.path.exists(cred_path):
        possible_paths = [
            settings.BASE_DIR / 'firebase-service-account.json',
            settings.BASE_DIR / 'serviceAccountKey.json',
            settings.BASE_DIR / 'smartkuri-firebase-adminsdk.json',
        ]
        # Search for any *-firebase-adminsdk-*.json in BASE_DIR
        matched = glob.glob(str(settings.BASE_DIR / '*firebase-adminsdk*.json'))
        possible_paths.extend([Path(p) for p in matched])

        for p in possible_paths:
            if p.exists():
                cred_path = str(p)
                break

    if cred_path and os.path.exists(cred_path):
        try:
            cred = credentials.Certificate(cred_path)
            app = firebase_admin.initialize_app(cred)
            logger.info(f"Firebase Admin initialized successfully using service account: {cred_path}")
            return app
        except Exception as e:
            logger.error(f"Failed to initialize Firebase Admin with credentials {cred_path}: {e}")

    # Fallback attempt
    try:
        app = firebase_admin.initialize_app()
        logger.info("Firebase Admin initialized with default credentials")
        return app
    except Exception as e:
        logger.warning(
            f"Firebase default app initialization failed: {e}. "
            f"To enable FCM push notifications, please place 'firebase-service-account.json' in {settings.BASE_DIR}"
        )
        return None


def is_fcm_configured():
    """Returns True if Firebase Admin is ready to send notifications."""
    app = get_firebase_app()
    return app is not None


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

    app = get_firebase_app()
    if not app:
        logger.warning(
            f"Cannot send push to {user.username}: Firebase Admin not initialized. "
            f"Place 'firebase-service-account.json' in {settings.BASE_DIR}."
        )
        return 0

    success_count = 0
    clean_data = {str(k): str(v) for k, v in (data or {}).items()}

    # Android specific config: channel matched with Flutter app
    android_config = messaging.AndroidConfig(
        priority='high',
        notification=messaging.AndroidNotification(
            channel_id='smartkuri_alerts_channel_v3',
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
            response = messaging.send(message, app=app)
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

