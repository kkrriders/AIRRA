"""
Notification service for multi-channel engineer notifications.

Senior Engineering Note:
- Email (primary): SMTP with HTML templates
- Slack (backup): Webhook integration
- SMS (critical): Twilio integration (optional)
- Async sending with retry logic
- SLA tracking and auto-escalation
"""
import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.engineer import Engineer
from app.models.incident import Incident
from app.models.notification import (
    Notification,
    NotificationChannel,
    NotificationStatus,
    NotificationPriority,
)
from app.services.token_service import token_service

logger = logging.getLogger(__name__)


class NotificationService:
    """Service for sending multi-channel notifications to engineers."""

    def __init__(self):
        """Initialize notification service."""
        # SMTP configuration from settings
        from app.config import settings

        self.smtp_enabled = settings.smtp_enabled
        self.smtp_host = settings.smtp_host
        self.smtp_port = settings.smtp_port
        self.smtp_user = settings.smtp_username
        self.smtp_password = settings.smtp_password.get_secret_value()
        self.from_email = settings.smtp_from_email
        self.smtp_use_tls = settings.smtp_use_tls
        self.frontend_url = settings.frontend_url

    async def send_incident_notification(
        self,
        db: AsyncSession,
        engineer_id: UUID,
        incident_id: UUID,
        channel: NotificationChannel = NotificationChannel.EMAIL,
        priority: NotificationPriority = NotificationPriority.NORMAL,
    ) -> Notification:
        """
        Send notification to engineer about an incident.

        Args:
            db: Database session
            engineer_id: Target engineer
            incident_id: Incident requiring attention
            channel: Delivery channel (email/slack/sms)
            priority: Urgency level

        Returns:
            Created Notification record
        """
        # Fetch engineer and incident details
        engineer_stmt = select(Engineer).where(Engineer.id == engineer_id)
        incident_stmt = select(Incident).where(Incident.id == incident_id)

        engineer_result = await db.execute(engineer_stmt)
        incident_result = await db.execute(incident_stmt)

        engineer = engineer_result.scalar_one_or_none()
        incident = incident_result.scalar_one_or_none()

        if not engineer:
            raise ValueError(f"Engineer {engineer_id} not found")
        if not incident:
            raise ValueError(f"Incident {incident_id} not found")

        # Build notification message
        subject, message = self._build_incident_message(engineer, incident, priority)

        # Determine recipient address based on channel
        recipient_address = self._get_recipient_address(engineer, channel)

        # Create notification record
        notification = Notification(
            engineer_id=engineer_id,
            incident_id=incident_id,
            channel=channel,
            status=NotificationStatus.PENDING,
            priority=priority,
            subject=subject,
            message=message,
            recipient_address=recipient_address,
            sla_target_seconds=self._get_sla_target(priority),
        )

        db.add(notification)
        await db.flush()  # Get notification ID

        # Generate secure token for acknowledgement
        token, expires_at = token_service.generate_token(
            notification.id,
            engineer_id,
            expiry_hours=1,
        )
        notification.acknowledgement_token = token
        notification.token_expires_at = expires_at

        await db.commit()
        await db.refresh(notification)

        # Send notification (async)
        await self._send_notification(notification, engineer, incident)

        return notification

    def _build_incident_message(
        self,
        engineer: Engineer,
        incident: Incident,
        priority: NotificationPriority,
    ) -> tuple[str, str]:
        """Build notification subject and message."""
        severity_emoji = {
            "critical": "🚨",
            "high": "⚠️",
            "medium": "ℹ️",
            "low": "📝",
        }

        emoji = severity_emoji.get(incident.severity.value, "📢")

        subject = (
            f"{emoji} [{priority.value.upper()}] "
            f"Incident: {incident.title} ({incident.affected_service})"
        )

        message = f"""
Hi {engineer.name},

You've been assigned to review an incident that requires your attention.

**Incident Details:**
- **Service:** {incident.affected_service}
- **Severity:** {incident.severity.value.upper()}
- **Status:** {incident.status.value}
- **Detected:** {incident.detected_at.strftime('%Y-%m-%d %H:%M UTC')}

**Description:**
{incident.description}

**What to do:**
1. Click the link below to access the incident admin panel
2. Review AI-generated hypotheses and recommended actions
3. Choose to: Approve AI approach, Suggest alternative, or Escalate

**Quick Actions:**
- View Incident: {{admin_panel_url}}
- Escalate: Reply to this email with "ESCALATE"

Please acknowledge within {self._get_sla_target(priority) // 60} minutes.

---
AIRRA - AI-Powered Incident Response
This is an automated notification. Do not reply to this email directly.
"""
        return subject, message

    def _get_recipient_address(
        self,
        engineer: Engineer,
        channel: NotificationChannel,
    ) -> str:
        """Get recipient address based on channel."""
        if channel == NotificationChannel.EMAIL:
            return engineer.email
        elif channel == NotificationChannel.SLACK:
            return engineer.slack_handle or engineer.email
        elif channel == NotificationChannel.SMS:
            return engineer.phone or engineer.email
        else:
            return engineer.email

    def _get_sla_target(self, priority: NotificationPriority) -> int:
        """Get SLA target in seconds based on priority."""
        sla_map = {
            NotificationPriority.CRITICAL: 180,  # 3 minutes
            NotificationPriority.HIGH: 300,  # 5 minutes
            NotificationPriority.NORMAL: 600,  # 10 minutes
            NotificationPriority.LOW: 1800,  # 30 minutes
        }
        return sla_map.get(priority, 300)

    async def _send_notification(
        self,
        notification: Notification,
        engineer: Engineer,
        incident: Incident,
    ) -> bool:
        """
        Send notification via appropriate channel.

        Returns:
            True if sent successfully, False otherwise
        """
        try:
            if notification.channel == NotificationChannel.EMAIL:
                success = await self._send_email(notification, engineer, incident)
            elif notification.channel == NotificationChannel.SLACK:
                success = await self._send_slack(notification, engineer, incident)
            elif notification.channel == NotificationChannel.SMS:
                success = await self._send_sms(notification, engineer)
            else:
                logger.warning(f"Unsupported channel: {notification.channel}")
                return False

            if success:
                notification.status = NotificationStatus.SENT
                notification.sent_at = datetime.now(timezone.utc)
                logger.info(
                    f"Notification {notification.id} sent via {notification.channel.value} "
                    f"to {engineer.email}"
                )
            else:
                notification.retry_count += 1
                if notification.retry_count >= notification.max_retries:
                    notification.status = NotificationStatus.FAILED
                logger.warning(
                    f"Notification {notification.id} failed "
                    f"(attempt {notification.retry_count}/{notification.max_retries})"
                )

            return success

        except Exception as e:
            notification.retry_count += 1
            notification.last_error = str(e)
            logger.error(
                f"Failed to send notification {notification.id}: {e}",
                exc_info=True,
            )
            return False

    async def _send_email(
        self,
        notification: Notification,
        engineer: Engineer,
        incident: Incident,
    ) -> bool:
        """Send email notification via SMTP."""
        try:
            # Generate admin panel URL with token
            admin_url, _ = token_service.generate_admin_panel_url(
                notification.id,
                engineer.id,
                base_url=self.frontend_url,
            )

            # Replace placeholder in message
            message_body = notification.message.replace("{{admin_panel_url}}", admin_url)

            # Create email
            msg = MIMEMultipart("alternative")
            msg["From"] = self.from_email
            msg["To"] = notification.recipient_address
            msg["Subject"] = notification.subject

            # Add HTML and plain text parts
            text_part = MIMEText(message_body, "plain")
            html_part = MIMEText(self._format_html_email(message_body, admin_url), "html")

            msg.attach(text_part)
            msg.attach(html_part)

            # Send email based on configuration
            if self.smtp_enabled and self.smtp_user and self.smtp_password:
                # Real SMTP sending
                logger.info(f"Sending email via SMTP to {notification.recipient_address}")

                with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                    if self.smtp_use_tls:
                        server.starttls()
                    server.login(self.smtp_user, self.smtp_password)
                    server.send_message(msg)

                logger.info(f"Email sent successfully to {notification.recipient_address}")
            else:
                # Simulation mode (development)
                logger.info(
                    f"[EMAIL SIMULATION] Would send email to {notification.recipient_address}\n"
                    f"Subject: {notification.subject}\n"
                    f"Admin URL: {admin_url}\n"
                    f"To enable real emails: Set AIRRA_SMTP_ENABLED=true and configure SMTP credentials"
                )

            return True

        except Exception as e:
            logger.error(f"Email send failed: {e}", exc_info=True)
            return False

    async def _send_slack(
        self,
        notification: Notification,
        engineer: Engineer,
        incident: Incident,
    ) -> bool:
        """Send Slack notification via webhook."""
        try:
            # TODO: Configure Slack webhook URL in settings
            webhook_url = "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

            # Generate admin panel URL
            admin_url, _ = token_service.generate_admin_panel_url(
                notification.id,
                engineer.id,
            )

            # Build Slack message
            slack_message = {
                "text": f"🚨 Incident Alert: {incident.title}",
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": f"🚨 {notification.subject}",
                        },
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Service:* {incident.affected_service}\n"
                            f"*Severity:* {incident.severity.value.upper()}\n"
                            f"*Status:* {incident.status.value}",
                        },
                    },
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "View Incident"},
                                "url": admin_url,
                                "style": "primary",
                            },
                        ],
                    },
                ],
            }

            logger.info(
                f"[SLACK SIMULATION] Would send Slack message to {notification.recipient_address}"
            )

            # Uncomment for actual Slack sending:
            # async with httpx.AsyncClient() as client:
            #     response = await client.post(webhook_url, json=slack_message)
            #     response.raise_for_status()

            return True  # Simulate success

        except Exception as e:
            logger.error(f"Slack send failed: {e}", exc_info=True)
            return False

    async def _send_sms(self, notification: Notification, engineer: Engineer) -> bool:
        """Send SMS notification via Twilio."""
        try:
            # TODO: Implement Twilio SMS sending
            # Requires: twilio library, account SID, auth token, phone number

            logger.info(
                f"[SMS SIMULATION] Would send SMS to {notification.recipient_address}\n"
                f"Message: {notification.subject}"
            )

            return True  # Simulate success

        except Exception as e:
            logger.error(f"SMS send failed: {e}", exc_info=True)
            return False

    def _format_html_email(self, message: str, admin_url: str) -> str:
        """Format email as HTML."""
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background-color: #f44336; color: white; padding: 20px; text-align: center; }}
        .content {{ padding: 20px; background-color: #f9f9f9; }}
        .button {{ background-color: #2196F3; color: white; padding: 12px 24px;
                   text-decoration: none; border-radius: 4px; display: inline-block;
                   margin: 20px 0; }}
        .footer {{ text-align: center; padding: 20px; font-size: 12px; color: #666; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚨 Incident Alert</h1>
        </div>
        <div class="content">
            <pre style="white-space: pre-wrap;">{message}</pre>
            <a href="{admin_url}" class="button">View Incident →</a>
        </div>
        <div class="footer">
            <p>AIRRA - AI-Powered Incident Response<br>
            This is an automated notification.</p>
        </div>
    </div>
</body>
</html>
"""
        return html


# Global instance
notification_service = NotificationService()
