
import json
from uuid import UUID
from pywebpush import webpush, WebPushException
from typing import List, Optional
from datetime import datetime
import pytz

from app.config import settings
from app.database import db_manager
from app.utils.logging import logger
from app.auth.schemas import UserPublic
from app.chat.schemas import MessageInDB

class NotificationService:
    def __init__(self):
        self.vapid_private_key = settings.VAPID_PRIVATE_KEY
        self.vapid_admin_email = settings.VAPID_ADMIN_EMAIL

    def is_configured(self) -> bool:
        return bool(self.vapid_private_key and self.vapid_admin_email)

    async def _get_active_subscriptions(self, user_id: UUID) -> List[dict]:
        try:
            resp = await db_manager.admin_client.table("push_subscriptions").select("*").eq("user_id", str(user_id)).eq("is_active", True).execute()
            return resp.data or []
        except Exception as e:
            logger.error(f"Error fetching subscriptions for user {user_id}: {e}")
            return []

    async def _get_user_notification_settings(self, user_id: UUID) -> Optional[dict]:
        try:
            resp = await db_manager.get_table("user_notification_settings").select("*").eq("user_id", str(user_id)).maybe_single().execute()
            return resp.data
        except Exception as e:
            logger.error(f"Error fetching notification settings for user {user_id}: {e}")
            return None

    def _is_in_quiet_hours(self, settings_data: dict) -> bool:
        if not settings_data.get("quiet_hours_enabled"): return False
        tz_str = settings_data.get("timezone", "UTC")
        try:
            user_tz = pytz.timezone(tz_str)
        except pytz.UnknownTimeZoneError:
            user_tz = pytz.utc
        
        now_user_time = datetime.now(user_tz)
        q_start_str = settings_data.get("quiet_hours_start")
        q_end_str = settings_data.get("quiet_hours_end")
        if not q_start_str or not q_end_str: return False
        
        q_start = datetime.strptime(q_start_str, '%H:%M:%S').time()
        q_end = datetime.strptime(q_end_str, '%H:%M:%S').time()

        if settings_data.get("quiet_hours_weekdays_only") and now_user_time.weekday() >= 5: return False
        current_time = now_user_time.time()
        if q_start <= q_end: return q_start <= current_time <= q_end
        else: return current_time >= q_start or current_time <= q_end

    def _send_web_push(self, subscription_info: dict, payload: str):
        sub_info_for_webpush = {"endpoint": subscription_info["endpoint"], "keys": {"p256dh": subscription_info["p256dh_key"], "auth": subscription_info["auth_key"]}}
        try:
            webpush(subscription_info=sub_info_for_webpush, data=payload, vapid_private_key=self.vapid_private_key, vapid_claims={"sub": self.vapid_admin_email})
        except WebPushException as ex:
            logger.error(f"WebPushException for endpoint {subscription_info['endpoint']}: {ex}")
            if ex.response and ex.response.status_code == 410:
                logger.info(f"Subscription expired for endpoint {subscription_info['endpoint']}. Deactivating.")
        except Exception as e:
            logger.error(f"Generic error sending push to {subscription_info['endpoint']}: {e}")

    async def _send_notification_to_user(self, user_id: UUID, notification_type: str, payload_data: dict):
        if not self.is_configured(): return
        
        settings = await self._get_user_notification_settings(user_id)
        if not settings or not settings.get(notification_type, False): return
        
        if settings.get("is_dnd_enabled", False):
            logger.info(f"Notification to user {user_id} suppressed due to DND mode.")
            return

        if self._is_in_quiet_hours(settings):
            logger.info(f"Notification to user {user_id} suppressed due to quiet hours.")
            return

        subscriptions = await self._get_active_subscriptions(user_id)
        if not subscriptions: return
            
        payload_json = json.dumps(payload_data)
        for sub in subscriptions:
            self._send_web_push(sub, payload_json)
    
    async def _get_recipients_for_chat(self, chat_id: UUID, exclude_user_id: UUID) -> List[UUID]:
        try:
            resp = await db_manager.get_table("chat_participants").select("user_id").eq("chat_id", str(chat_id)).neq("user_id", str(exclude_user_id)).execute()
            return [UUID(row['user_id']) for row in resp.data]
        except Exception as e:
            logger.error(f"Error fetching recipients for chat {chat_id}: {e}")
            return []

    def _get_message_notification_text(self, sender_name: str, message: MessageInDB) -> str:
        subtype = message.message_subtype
        if subtype == "sticker": return f"{sender_name} sent you a sticker."
        if subtype == "image": return f"{sender_name} sent you an image."
        if subtype == "document": return f"{sender_name} sent a document: {message.document_name or 'file'}."
        if subtype == "voice_message": return f"{sender_name} sent you a voice message."
        if subtype == "clip": return f"{sender_name} sent you a {message.clip_type} clip."
        if message.text: return message.text[:100]
        return "You have a new message."

    async def send_new_message_notification(self, sender: UserPublic, chat_id: UUID, message: MessageInDB):
        recipients = await self._get_recipients_for_chat(chat_id, sender.id)
        notification_body = self._get_message_notification_text(sender.display_name, message)
        payload = {"type": "message", "title": f"New message from {sender.display_name}", "options": {"body": notification_body, "icon": sender.avatar_url or "/icons/icon-192x192.png", "badge": "/icons/badge-96x96.png", "tag": f"conversation-{chat_id}", "data": {"conversationId": str(chat_id)}}}
        for recipient_id in recipients:
            await self._send_notification_to_user(recipient_id, "messages", payload)

    async def send_mood_change_notification(self, user: UserPublic, new_mood: str):
        if not user.partner_id: return
        payload = {"type": "mood_update", "title": f"{user.display_name} has updated their mood!", "options": {"body": f"They are now feeling: {new_mood}", "icon": user.avatar_url, "tag": f"mood-{user.id}"}}
        await self._send_notification_to_user(user.partner_id, "mood_updates", payload)

    async def send_thinking_of_you_notification(self, sender: UserPublic, recipient_id: UUID):
         payload = {"type": "thinking_of_you", "title": f"{sender.display_name} is thinking of you!", "options": {"body": "Send a thought back from the app.", "icon": sender.avatar_url, "badge": "/icons/badge-96x96.png", "tag": f"ping-{sender.id}-{recipient_id}", "data": {"senderId": str(sender.id)}}}
         await self._send_notification_to_user(recipient_id, "thinking_of_you", payload)

notification_service = NotificationService()
