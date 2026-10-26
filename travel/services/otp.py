import secrets
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import send_mail
from django.utils import timezone
from travel.models import OTPVerification


class OTPRequestThrottled(Exception):
    """Raised when a new OTP is requested before the resend cooldown ends."""


def issue_otp(user, purpose):
    latest = OTPVerification.objects.filter(user=user, purpose=purpose).order_by("-created_at").first()
    if latest and (timezone.now() - latest.created_at).total_seconds() < 60:
        raise OTPRequestThrottled("Please wait 60 seconds before requesting another code.")
    OTPVerification.objects.filter(user=user, purpose=purpose, used=False).update(used=True)
    code = f"{secrets.randbelow(1000000):06d}"
    record = OTPVerification.objects.create(
        user=user,
        purpose=purpose,
        code_hash=make_password(code),
        expires_at=timezone.now() + timedelta(minutes=5),
    )
    if getattr(settings, "DEBUG", False):
        print(f"\n=======================================================")
        print(f" [SmartTrip AI OTP] Debug / Console Delivery")
        print(f" Purpose   : {purpose.upper()}")
        print(f" Recipient : {user.email}")
        print(f" >>> OTP CODE : {code} <<<")
        print(f"=======================================================\n")
    try:
        sent = send_mail(
            subject="SmartTrip AI verification code",
            message=f"Your SmartTrip AI OTP is {code}. It expires in 5 minutes. Do not share this code.",
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "SmartTrip AI <no-reply@smarttrip.local>"),
            recipient_list=[user.email],
            fail_silently=False,
        )
        if sent != 1:
            raise RuntimeError("The email service did not confirm delivery.")
    except Exception as email_err:
        if getattr(settings, "DEBUG", False):
            import logging
            logging.getLogger("smarttrip").warning(
                f"[SmartTrip AI] Email delivery issue ({email_err}). Console OTP: {code}"
            )
            return record
        record.delete()
        raise
    return record


def verify_otp(user, purpose, code, otp_id=None):
    records = OTPVerification.objects.filter(
        user=user, purpose=purpose, used=False, expires_at__gt=timezone.now()
    )
    if otp_id is not None:
        records = records.filter(pk=otp_id)
    record = records.first()
    if not record:
        return False, "The OTP has expired or is invalid. Request a new code."
    if record.attempts >= 5:
        return False, "Too many attempts. Request a new OTP."
    record.attempts += 1
    if not check_password(code.strip(), record.code_hash):
        record.save(update_fields=["attempts"])
        return False, "Incorrect OTP."
    record.used = True
    record.save(update_fields=["attempts", "used"])
    return True, "OTP verified."
