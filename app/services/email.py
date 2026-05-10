"""Email sender. En dev (SMTP_HOST=__console__) imprime al log."""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from ..config import settings


def send_email(to_email: str, subject: str, html: str, text: str | None = None) -> None:
    if settings.smtp_host == "__console__":
        body = text or _strip_html(html)
        message = (
            "\n" + "=" * 60
            + "\n[EMAIL DEV CONSOLE - no se envia realmente]"
            + f"\nTo:      {to_email}"
            + f"\nSubject: {subject}"
            + "\n" + "-" * 60
            + f"\n{body}"
            + "\n" + "=" * 60 + "\n"
        )
        # Encode-safe write para consolas Windows cp1252
        try:
            print(message)
        except UnicodeEncodeError:
            import sys
            sys.stdout.buffer.write(message.encode("utf-8", errors="replace"))
            sys.stdout.buffer.write(b"\n")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from_email
    msg["To"] = formataddr((to_email.split("@")[0], to_email))

    if text:
        msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.sendmail(settings.smtp_from_email, [to_email], msg.as_string())


def _strip_html(html: str) -> str:
    import re

    return re.sub(r"<[^>]+>", "", html).strip()
