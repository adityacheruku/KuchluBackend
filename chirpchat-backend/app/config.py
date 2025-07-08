from pydantic_settings import BaseSettings
from typing import Optional
from dotenv import load_dotenv
load_dotenv()
class Settings(BaseSettings):
    SUPABASE_URL: str
    SUPABASE_ANON_KEY: str
    SUPABASE_SERVICE_ROLE_KEY: str
    REDIS_URL: str = "redis://localhost:6379/0"
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7
    CLOUDINARY_CLOUD_NAME: str
    CLOUDINARY_API_KEY: str
    CLOUDINARY_API_SECRET: str
    CLOUDINARY_WEBHOOK_URL: Optional[str] = None
    API_BASE_URL: str = "http://localhost:8000"
    HUGGINGFACE_API_KEY: Optional[str] = None
    HUGGINGFACE_MOOD_MODEL_URL: Optional[str] = None
    NOTIFICATION_EMAIL_TO: Optional[str] = None
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_SENDER_EMAIL: Optional[str] = None
    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    VAPID_PUBLIC_KEY: Optional[str] = None
    VAPID_PRIVATE_KEY: Optional[str] = None
    VAPID_ADMIN_EMAIL: Optional[str] = "mailto:admin@example.com"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    SERVER_INSTANCE_ID: str = "default-instance-01"
    
    # Firebase Configuration
    FIREBASE_PROJECT_ID: str = "kuchlu-8791e"
    FIREBASE_PRIVATE_KEY_ID: str = ""
    FIREBASE_PRIVATE_KEY: str = ""
    FIREBASE_CLIENT_EMAIL: str = ""
    FIREBASE_CLIENT_ID: str = ""
    FIREBASE_AUTH_URI: str = "https://accounts.google.com/o/oauth2/auth"
    FIREBASE_TOKEN_URI: str = "https://oauth2.googleapis.com/token"
    FIREBASE_AUTH_PROVIDER_X509_CERT_URL: str = "https://www.googleapis.com/oauth2/v1/certs"
    FIREBASE_CLIENT_X509_CERT_URL: str = ""
    
    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
