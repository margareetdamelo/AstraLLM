"""
飞书登录认证模块
支持飞书扫码登录
"""
import hashlib
import secrets
import time
import requests
import json
from datetime import datetime, timedelta
from typing import Optional, Dict
from loguru import logger


# 飞书应用配置
FEISHU_APP_ID = "cli_a923ab78f1625e1b"
FEISHU_APP_SECRET = "VoLtveX30VBVyKiseDAZwcu4aLznoWvZ"
FEISHU_REDIRECT_URI = "https://quant-astrallm.goldwarts.com/auth/feishu/callback"

# 会话存储 (生产环境应使用Redis)
feishu_sessions = {}  # tmp_openid -> {code_verifier, expires_at, user_info}
auth_codes = {}  # auth_code -> {tmp_openid, expires_at}


class FeishuAuth:
    """飞书认证类"""
    
    def __init__(self):
        self.app_id = FEISHU_APP_ID
        self.app_secret = FEISHU_APP_SECRET
        self.redirect_uri = FEISHU_REDIRECT_URI
    
    def get_authorization_url(self, state: str) -> str:
        """获取授权URL"""
        # 飞书开放平台应用扫码登录URL
        base_url = "https://open.feishu.cn/open-apis/authen/v1/authorize"
        params = f"?app_id={self.app_id}&redirect_uri={self.redirect_uri}&state={state}"
        return base_url + params
    
    def get_qrcode_url(self, state: str) -> str:
        """获取扫码登录二维码URL"""
        # 飞书小程序扫码登录二维码
        return f"https://open.feishu.cn/document/ukTMukTMukTM/uADOwUjLwgDM14CM4ATN?lang=zh-CN"
    
    def exchange_code_for_user(self, code: str) -> Optional[Dict]:
        """用授权码换取用户信息"""
        url = "https://open.feishu.cn/open-apis/authen/v1/access_token"
        
        headers = {
            "Content-Type": "application/json"
        }
        
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
            
            if data.get("code") == 0:
                return data.get("data", {})
            else:
                logger.error(f"Feishu auth failed: {data}")
                return None
                
        except Exception as e:
            logger.error(f"Feishu auth error: {e}")
            return None
    
    def get_user_info(self, access_token: str) -> Optional[Dict]:
        """获取用户信息"""
        url = "https://open.feishu.cn/open-apis/authen/v1/user_info"
        
        headers = {
            "Authorization": f"Bearer {access_token}"
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            data = response.json()
            
            if data.get("code") == 0:
                return data.get("data", {})
            else:
                return None
                
        except Exception as e:
            logger.error(f"Get user info error: {e}")
            return None
    
    def create_session(self, user_info: Dict) -> str:
        """创建会话"""
        session_token = secrets.token_hex(32)
        expires_at = datetime.now() + timedelta(days=7)
        
        feishu_sessions[session_token] = {
            "user_info": user_info,
            "expires_at": expires_at,
            "created_at": datetime.now()
        }
        
        return session_token
    
    def verify_session(self, token: str) -> Optional[Dict]:
        """验证会话"""
        session = feishu_sessions.get(token)
        
        if not session:
            return None
        
        if datetime.now() > session["expires_at"]:
            del feishu_sessions[token]
            return None
        
        return session["user_info"]
    
    def revoke_session(self, token: str):
        """撤销会话"""
        if token in feishu_sessions:
            del feishu_sessions[token]


# 全局认证实例
feishu_auth = FeishuAuth()


def generate_login_qr() -> Dict:
    """生成登录二维码信息"""
    state = secrets.token_hex(16)
    
    # 存储state用于验证
    auth_codes[state] = {
        "created_at": datetime.now(),
        "expires_at": datetime.now() + timedelta(minutes=5)
    }
    
    return {
        "state": state,
        "qrcode_url": feishu_auth.get_qrcode_url(state),
        "auth_url": feishu_auth.get_authorization_url(state),
        "expires_in": 300
    }


def verify_auth_code(code: str, state: str) -> Optional[str]:
    """验证授权码并返回session token"""
    # 验证state
    state_data = auth_codes.get(state)
    if not state_data:
        return None
    
    if datetime.now() > state_data["expires_at"]:
        del auth_codes[state]
        return None
    
    # 交换code获取用户信息
    user_data = feishu_auth.exchange_code_for_user(code)
    if not user_data:
        return None
    
    access_token = user_data.get("access_token")
    if not access_token:
        return None
    
    # 获取用户详细信息
    user_info = feishu_auth.get_user_info(access_token)
    if not user_info:
        # 使用基本返回
        user_info = {
            "open_id": user_data.get("open_id", "unknown"),
            "union_id": user_data.get("union_id", ""),
            "name": user_data.get("name", "User")
        }
    
    # 创建会话
    session_token = feishu_auth.create_session(user_info)
    
    # 清理auth code
    del auth_codes[state]
    
    return session_token


def get_current_user(token: str) -> Optional[Dict]:
    """获取当前用户"""
    return feishu_auth.verify_session(token)
