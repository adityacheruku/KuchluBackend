
import enum

# Enums can remain as they are pure Python
class ClipTypeEnum(str, enum.Enum):
    audio = "audio"
    video = "video"

# SQLAlchemy models (Chat, Message, chat_participants table) are removed.
# The database schema (tables, columns, relationships) is now defined and managed directly in Supabase.
# Pydantic models in app.chat.schemas will be used to define data structures for API requests/responses.
