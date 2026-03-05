"""
飞书登录认证模块
支持飞书扫码登录和飞书内应用登录
"""
import secrets
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict
from loguru import logger


FEISHU_APP_ID = "cli_a923ab78f1625e1b"
FEISHU_APP_SECRET = "VoLtveX30VBVyKiseDAZwcu4aLznoWvZ"
FEISHU_REDIRECT_URI = "https://quant-astrallm.goldwarts.com/auth/lark/callback"

feishu_sessions = {}
auth_codes = {}


class FeishuAuth:
    def __init__(self):
        self.app_id = FEISHU_APP_ID
        self.app_secret = FEISHU_APP_SECRET
        self.redirect_uri = FEISHU_REDIRECT_URI
    
    def get_authorization_url(self, state: str) -> str:
        base_url = "https://open.feishu.cn/open-apis/authen/v1/authorize"
        return f"{base_url}?app_id={self.app_id}&redirect_uri={self.redirect_uri}&state={state}"
    
    def get_qrcode_url(self, state: str) -> str:
        return f"https://open.feishu.cn/open-apis/authen/v1/authorize?app_id={self.app_id}&redirect_uri={self.redirect_uri}&state={state}"
    
    def get_login_page_url(self, state: str) -> str:
        return f"https://open.feishu.cn/open-apis/authen/v1/index.html?app_id={self.app_id}&redirect_uri={self.redirect_uri}&state={state}"
    
    def get_mini_app_login_url(self, state: str) -> str:
        return f"https://open.feishu.cn/open-apis/authen/v1/authorize?app_id={self.app_id}&redirect_uri={self.redirect_uri}&state={state}&type=miniapp"
    
    def exchange_code_for_token(self, code: str) -> Optional[Dict]:
        url = "https://open.feishu.cn/open-apis/authen/v1/access_token"
        headers = {"Content-Type": "application/json"}
        payload = {
            "grant_type": "authorization_code",
            "client_id": self.app_id,
            "client_secret": self.app_secret,
            "code": code,
            "redirect_uri": self.redirect_uri
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            data = response.json()
            logger.info(f"Feishu token response: {data}")
            
            if data.get("code") == 0:
                return data.get("data", {})
            else:
                logger.error(f"Feishu auth failed: {data}")
                return None
        except Exception as e:
            logger.error(f"Feishu auth error: {e}")
            return None
    
    def get_user_info(self, access_token: str) -> Optional[Dict]:
        url = "https://open.feishu.cn/open-apis/authen/v1/user_info"
        headers = {"Authorization": f"Bearer {access_token}"}
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            data = response.json()
            
            if data.get("code") == 0:
                return data.get("data", {})
            return None
        except Exception as e:
            logger.error(f"Get user info error: {e}")
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


feishu_auth = FeishuAuth()


def generate_login_qr() -> Dict:
    state = secrets.token_hex(16)
    
    auth_codes[state] = {
        "created_at": datetime.now(),
        "expires_at": datetime.now() + timedelta(minutes=5)
    }
    
    return {
        "state": state,
        "qrcode_url": feishu_auth.get_login_page_url(state),
        "auth_url": feishu_auth.get_authorization_url(state),
        "login_page_url": feishu_auth.get_login_page_url(state),
        "expires_in": 300
    }


def verify_auth_code(code: str, state: str = None) -> Optional[str]:
    if state:
        state_data = auth_codes.get(state)
        if state_data and datetime.now() > state_data["expires_at"]:
            del auth_codes[state]
            state_data = None
    
    token_data = feishu_auth.exchange_code_for_token(code)
    if not token_data:
        return None
    
    access_token = token_data.get("access_token")
    if not access_token:
        return None
    
    user_info = feishu_auth.get_user_info(access_token)
    if not user_info:
        user_info = {
            "open_id": token_data.get("open_id", "unknown"),
            "union_id": token_data.get("union_id", ""),
            "name": token_data.get("name", "User")
        }
    
    session_token = feishu_auth.create_session(user_info)
    
    if state and state in auth_codes:
        del auth_codes[state]
    
    return session_token


def get_current_user(token: str) -> Optional[Dict]:
    return feishu_auth.verify_session(token)
