"""Bounded request-driven SMTP delivery for workspace invitations."""
import asyncio
from email.message import EmailMessage

from app.config import settings


async def _send_message(message: EmailMessage) -> None:
    # Import lazily so database-only administration remains usable if deployment
    # dependencies are temporarily incomplete during an upgrade.
    import aiosmtplib

    call = aiosmtplib.send(
        message,
        hostname=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
        username=settings.SMTP_USERNAME,
        password=settings.SMTP_PASSWORD,
        start_tls=settings.SMTP_STARTTLS,
        timeout=settings.SMTP_TIMEOUT_SECONDS,
    )
    await asyncio.wait_for(call, timeout=settings.SMTP_TIMEOUT_SECONDS + 0.25)


async def send_workspace_invitation(recipient: str, workspace_name: str, role: str, token: str) -> None:
    url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/workspace-invitations/{token}"
    message = EmailMessage()
    message["From"] = settings.SMTP_SENDER
    message["To"] = recipient
    message["Subject"] = f"Invitation to {workspace_name}"
    message.set_content(
        f"You were invited to join {workspace_name} as {role}.\n\n"
        f"Open this private invitation link: {url}\n\n"
        "This message contains no financial information."
    )
    await _send_message(message)


async def send_workspace_added_notification(recipient: str, workspace_name: str, role: str) -> None:
    message = EmailMessage()
    message["From"] = settings.SMTP_SENDER
    message["To"] = recipient
    message["Subject"] = f"You were added to {workspace_name}"
    message.set_content(
        f"You were added to {workspace_name} as {role}.\n\n"
        f"Sign in to Spendy at {settings.PUBLIC_BASE_URL.rstrip('/')} to access the workspace.\n\n"
        "This message contains no financial information."
    )
    await _send_message(message)
