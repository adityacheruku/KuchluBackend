
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType
from pydantic import EmailStr
from typing import List, Optional
from app.config import settings
from app.utils.logging import logger # Assuming you have a logger setup
from pathlib import Path
import os

# Determine the base directory of the project if needed for templates
# For simple HTML string, it's not strictly necessary.
# BASE_DIR = Path(__file__).resolve().parent.parent # This would be app/

async def send_email_async(subject: str, email_to: EmailStr, body: str):
    logger.info(settings.SMTP_HOST, settings.SMTP_USER, settings.SMTP_PASSWORD, settings.SMTP_SENDER_EMAIL)
    if not all([settings.SMTP_HOST, settings.SMTP_USER, settings.SMTP_PASSWORD, settings.SMTP_SENDER_EMAIL]):
        logger.warning("SMTP settings or NOTIFICATION_EMAIL_TO not fully configured. Skipping email notification.")
        return

    conf = ConnectionConfig(
        MAIL_USERNAME=settings.SMTP_USER,
        MAIL_PASSWORD=settings.SMTP_PASSWORD,
        MAIL_FROM=settings.SMTP_SENDER_EMAIL,
        MAIL_PORT=settings.SMTP_PORT,
        MAIL_SERVER=settings.SMTP_HOST,
        MAIL_STARTTLS=settings.SMTP_TLS,
        MAIL_SSL_TLS=settings.SMTP_SSL,
        USE_CREDENTIALS=True,
        VALIDATE_CERTS=True, # Consider making this configurable for dev environments
        # TEMPLATE_FOLDER=Path(BASE_DIR, 'templates/email') # If using Jinja templates
    )

    message = MessageSchema(
        subject=subject,
        recipients=[email_to],
        body=body,
        subtype=MessageType.html 
    )

    fm = FastMail(conf)
    try:
        await fm.send_message(message)
        logger.info(f"Login notification email sent to {email_to} for subject: {subject}")
    except Exception as e:
        logger.error(f"Failed to send email to {email_to}: {e}")


async def send_login_notification_email(
    logged_in_user_name: str,
    logged_in_user_phone: Optional[str],
    login_time: str,
    client_host: Optional[str] = None # Optional client IP
):
    if not settings.NOTIFICATION_EMAIL_TO:
        logger.info("NOTIFICATION_EMAIL_TO not set. Skipping login notification email.")
        return

    subject = f"ChirpChat User Login: {logged_in_user_name}"
    
    phone_info = logged_in_user_phone if logged_in_user_phone else "N/A"
    
    ip_info_html = f"<p><strong>IP Address:</strong> {client_host}</p>" if client_host else ""

    html_body = f"""
    <html>
        <body>
            <h2>ChirpChat User Login Notification</h2>
            <p>A user has logged into ChirpChat:</p>
            <ul>
                <li><strong>Name:</strong> {logged_in_user_name}</li>
                <li><strong>Phone:</strong> {phone_info}</li>
                <li><strong>Login Time:</strong> {login_time} (UTC)</li>
            </ul>
            {ip_info_html}
            <p>This is an automated notification.</p>
        </body>
    </html>
    """
    try:
        await send_email_async(subject, settings.NOTIFICATION_EMAIL_TO, html_body)
    except Exception as e:
        # send_email_async already logs, but good to catch here too if needed
        logger.error(f"Error dispatching login notification for {logged_in_user_name}: {e}")

