from django.conf import settings
from django.core.mail import send_mail


class EmailService:
    """Thin wrapper over Django's send_mail. EMAIL_BACKEND defaults to the
    console backend in dev/test, so OTP codes never hit the app logger --
    they print directly to stdout, bypassing structured logging entirely.
    Swapping to real AWS SES later is an EMAIL_BACKEND change only, no
    call-site changes.
    """

    @staticmethod
    def send_otp_email(email: str, code: str) -> None:
        send_mail(
            subject="Your BOLO login code",
            message=f"Your OTP is {code}. It expires in 10 minutes.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
        )

    @staticmethod
    def send_task_reminder_email(email: str, task_title: str, message: str) -> None:
        send_mail(
            subject=f"Reminder: {task_title}",
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
        )
