"""
Lark登录认证模块
使用httpx直接调用API
"""
import secrets
import httpx
from datetime import datetime, timedelta
from typing import Optional, Dict
from loguru import logger


FEISHU_APP_ID = "cli_a923ab78f1625e1b"
FEISHU_APP_SECRET = "VoLtveX30VBVyKiseDAZwcu4aLznoWvZ"
FEISHU_REDIRECT_URI = "https://quant-astrallm.goldwarts.com/auth/lark/callback"

feishu_sessions = {}
auth_codes = {}


class LarkAuth:
    def __init__(self):
        self.app_id = FEISHU_APP_ID
        self.app_secret = FEISHU_APP_SECRET
        self.redirect_uri = FEISHU_REDIRECT_URI
        logger.info(f"LarkAuth initialized with app_id: {self.app_id}")
    
    def get_authorization_url(self, state: str) -> str:
        url = (
            "https://open.larksuite.com/open-apis/authen/v1/authorize"
            f"?app_id={self.app_id}"
            f"&redirect_uri={self.redirect_uri}"
            "&response_type=code"
        )
        return url
    
    def get_login_page_url(self, state: str) -> str:
        return self.get_authorization_url(state)
    
    def exchange_code_for_token(self, code: str) -> Optional[Dict]:
        token_url = "https://open.larksuite.com/open-apis/authen/v1/access_token"
        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }
        
        try:
            response = httpx.post(token_url, json=token_data, timeout=10)
            token_json = response.json()
            logger.info(f"Lark token response: {token_json}")
            
            if token_json.get("code") != 0:
                logger.error(f"Lark token failed: {token_json}")
                return None
            
            data = token_json.get("data", {})
            return {
                "access_token": data.get("access_token"),
                "token_type": data.get("token_type"),
                "expires_in": data.get("expires_in"),
                "refresh_token": data.get("refresh_token"),
                "open_id": data.get("open_id")
            }
                
        except Exception as e:
            logger.error(f"Lark token error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def get_user_info(self, access_token: str) -> Optional[Dict]:
        user_url = "https://open.larksuite.com/open-apis/contact/v3/users/me"
        user_headers = {"Authorization": f"Bearer {access_token}"}
        
        try:
            response = httpx.get(user_url, headers=user_headers, timeout=10)
            user_json = response.json()
            logger.info(f"Lark user response: {user_json}")
            
            if user_json.get("code") != 0:
                logger.error(f"Lark user info failed: {user_json}")
                return None
            
            user_data = user_json.get("data", {}).get("user", {})
            return {
                "open_id": user_data.get("open_id"),
                "user_id": user_data.get("user_id"),
                "name": user_data.get("name"),
                "email": user_data.get("email")
            }
                
        except Exception as e:
            logger.error(f"Lark user info error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def create_session(self, user_info: Dict) -> str:
        session_token = secrets.token_hex(32)
        expires_at = datetime.now() + timedelta(days=7)
        
        feishu_sessions[session_token] = {
            "user_info": user_info,
            "expires_at": expires_at,
            "created_at": datetime.now()
        }
        
        return session_token
    
    def verify_session(self, token: str) -> Optional[Dict]:
        session = feishu_sessions.get(token)
        
        if not session:
            return None
        
        if datetime.now() > session["expires_at"]:
            del feishu_sessions[token]
            return None
        
        return session["user_info"]


lark_auth = LarkAuth()


def generate_login_qr() -> Dict:
    state = secrets.token_hex(16)
    
    auth_codes[state] = {
        "created_at": datetime.now(),
        "expires_at": datetime.now() + timedelta(minutes=5)
    }
    
    return {
        "state": state,
        "login_page_url": lark_auth.get_login_page_url(state),
        "auth_url": lark_auth.get_authorization_url(state),
        "expires_in": 300
    }


def verify_auth_code(code: str, state: str = None) -> Optional[str]:
    if state:
        state_data = auth_codes.get(state)
        if state_data and datetime.now() > state_data["expires_at"]:
            del auth_codes[state]
            state_data = None
    
    token_data = lark_auth.exchange_code_for_token(code)
    if not token_data:
        return None
    
    access_token = token_data.get("access_token")
    if not access_token:
        return None
    
    user_info = lark_auth.get_user_info(access_token)
    if not user_info:
        user_info = {
            "open_id": token_data.get("open_id", "unknown"),
            "name": "User"
        }
    
    session_token = lark_auth.create_session(user_info)
    
    if state and state in auth_codes:
        del auth_codes[state]
    
    return session_token


def get_current_user(token: str) -> Optional[Dict]:
    return lark_auth.verify_session(token)
