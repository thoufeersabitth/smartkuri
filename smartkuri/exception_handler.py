import logging
import traceback
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from django.db import IntegrityError

logger = logging.getLogger(__name__)

def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is None:
        logger.error(f"Unhandled Exception in {context.get('view')}: {exc}", exc_info=True)
        traceback.print_exc()

        msg = str(exc)
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

        if isinstance(exc, IntegrityError) or "unique constraint" in msg.lower():
            status_code = status.HTTP_400_BAD_REQUEST
            msg = "A record with this phone number, email, or details already exists."
        elif "does not exist" in msg.lower():
            status_code = status.HTTP_404_NOT_FOUND
            msg = "The requested record was not found."

        return Response(
            {
                "detail": msg,
                "error_type": type(exc).__name__,
            },
            status=status_code
        )

    return response
