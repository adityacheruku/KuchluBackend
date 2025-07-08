import firebase_admin
from firebase_admin import credentials, auth
from app.config import settings
from app.utils.logging import logger
from typing import Optional, Dict, Any

class FirebaseService:
    def __init__(self):
        self._initialized = False
        self._initialize_firebase()
    
    def _initialize_firebase(self):
        """Initialize Firebase Admin SDK"""
        if self._initialized:
            return
            
        try:
            # Create credentials from environment variables
            cred_dict = {
                "type": "service_account",
                "project_id": settings.FIREBASE_PROJECT_ID,
                "private_key_id": settings.FIREBASE_PRIVATE_KEY_ID,
                "private_key": settings.FIREBASE_PRIVATE_KEY.replace('\\n', '\n') if settings.FIREBASE_PRIVATE_KEY else "",
                "client_email": settings.FIREBASE_CLIENT_EMAIL,
                "client_id": settings.FIREBASE_CLIENT_ID,
                "auth_uri": settings.FIREBASE_AUTH_URI,
                "token_uri": settings.FIREBASE_TOKEN_URI,
                "auth_provider_x509_cert_url": settings.FIREBASE_AUTH_PROVIDER_X509_CERT_URL,
                "client_x509_cert_url": settings.FIREBASE_CLIENT_X509_CERT_URL
            }
            
            # Check if we have the minimum required credentials
            if not all([settings.FIREBASE_PROJECT_ID, settings.FIREBASE_PRIVATE_KEY, settings.FIREBASE_CLIENT_EMAIL]):
                logger.warning("Firebase credentials not fully configured. Firebase auth will be disabled.")
                return
            
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
            self._initialized = True
            logger.info("Firebase Admin SDK initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Firebase Admin SDK: {e}")
            self._initialized = False
    
    def verify_id_token(self, id_token: str) -> Optional[Dict[str, Any]]:
        """Verify Firebase ID token and return decoded token data"""
        if not self._initialized:
            logger.error("Firebase not initialized. Cannot verify token.")
            return None
            
        try:
            decoded_token = auth.verify_id_token(id_token)
            logger.info(f"Firebase token verified for user: {decoded_token.get('uid')}")
            return decoded_token
        except Exception as e:
            logger.error(f"Failed to verify Firebase token: {e}")
            return None
    
    def get_user_by_uid(self, uid: str) -> Optional[Dict[str, Any]]:
        """Get Firebase user by UID"""
        if not self._initialized:
            logger.error("Firebase not initialized. Cannot get user.")
            return None
            
        try:
            user = auth.get_user(uid)
            return {
                "uid": user.uid,
                "phone_number": user.phone_number,
                "email": user.email,
                "display_name": user.display_name,
                "photo_url": user.photo_url,
                "email_verified": user.email_verified,
                "phone_number_verified": user.phone_number_verified
            }
        except Exception as e:
            logger.error(f"Failed to get Firebase user {uid}: {e}")
            return None

# Global instance
firebase_service = FirebaseService() 