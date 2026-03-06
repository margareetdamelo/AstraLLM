"""
Demo Dashboard - Runs without real Aster credentials

Shows dashboard with simulated data so you can see how it looks
"""
import sys
import threading
import time
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Dict, List
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from loguru import logger
import random
import os

# 导入飞书认证模块
feishu_auth_module = None
try:
    import core.feishu_auth as feishu_auth_module
    from core.feishu_auth import (
        generate_login_qr,
        verify_auth_code,
        get_current_user,
        feishu_sessions
    )
    FEISHU_ENABLED = True
    logger.info("Lark authentication enabled")
except Exception as e:
    FEISHU_ENABLED = False
    logger.error(f"Lark authentication module error: {e}")
    import traceback
    logger.error(traceback.format_exc())

# Session tokens (in production, use a proper session store)
sessions = {}  # token -> expiry time

# Initialize FastAPI
app = FastAPI(title="ASTER Trading Bot Demo")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simulated bot state
demo_state = {
    "running": True,
    "current_capital": 10000,
    "initial_capital": 10000,
    "total_pnl": 0,
    "daily_pnl": 0,
    "total_trades": 0,
    "winning_trades": 0,
    "losing_trades": 0,
    "open_positions": [],
    "recent_trades": [],
    "current_regime": "high_vol_trending",
    "regime_confidence": 0.85,
    "selected_strategy": "Breakout Scalping",
    "strategy_stats": {
        "Breakout Scalping": {
            "total_trades": 45,
            "win_rate": 0.64,
            "total_pnl": 2340,
            "avg_pnl": 52,
            "enabled": True
        },
        "Momentum Reversal": {
            "total_trades": 28,
            "win_rate": 0.57,
            "total_pnl": 1120,
            "avg_pnl": 40,
            "enabled": True
        },
        "Funding Arbitrage": {
            "total_trades": 12,
            "win_rate": 0.75,
            "total_pnl": 890,
            "avg_pnl": 74,
            "enabled": True
        },
        "Liquidation Cascade": {
            "total_trades": 8,
            "win_rate": 0.50,
            "total_pnl": -120,
            "avg_pnl": -15,
            "enabled": False
        },
        "Market Making": {
            "total_trades": 67,
            "win_rate": 0.78,
            "total_pnl": 1870,
            "avg_pnl": 28,
            "enabled": True
        }
    }
}


def simulate_market_updates():
    """Simulate market activity"""
    regimes = ["high_vol_trending", "low_vol_ranging", "momentum_exhaustion", "mixed"]
    strategies = ["Breakout Scalping", "Momentum Reversal", "Market Making", "Funding Arbitrage"]
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    while True:
        time.sleep(15)  # Update every 15 seconds

        # Randomly change regime sometimes
        if random.random() < 0.1:  # 10% chance
            demo_state["current_regime"] = random.choice(regimes)
            demo_state["selected_strategy"] = random.choice(strategies)
            demo_state["regime_confidence"] = random.uniform(0.6, 0.95)
            logger.info(f"Regime changed to: {demo_state['current_regime']}")

        # Simulate new trade sometimes
        if random.random() < 0.15:  # 15% chance
            
            symbol = random.choice(symbols)
            if symbol == "BTCUSDT":
                base_price = random.uniform(42000, 45000)
            elif symbol == "ETHUSDT":
                base_price = random.uniform(2800, 3200)
            else:
                base_price = random.uniform(95, 110)
            
            leverage = random.choice([5, 10, 15, 20])
            side = random.choice(["LONG", "SHORT"])
            is_win = random.random() < 0.6
            
            if is_win:
                pnl_percentage = random.uniform(1, 5)  # 1-5%
            else:
                pnl_percentage = random.uniform(-5, -1)  # -1 to -5%
            
            entry_price = base_price
            # 根据多空方向和盈亏计算出场价格
            # LONG: 盈利=价格上涨, 亏损=价格下跌
            # SHORT: 盈利=价格下跌, 亏损=价格上涨
            if side == "LONG":
                # 多单
                exit_price = entry_price * (1 + pnl_percentage / 100)
            else:
                # 空单: pnl%正=盈利(价格跌), pnl%负=亏损(价格涨)
                exit_price = entry_price * (1 - pnl_percentage / 100)
            
            quantity = random.uniform(0.01, 0.1)
            # Position Value = 价格 × 数量（不乘杠杆）
            position_value = entry_price * quantity
            
            # PnL计算统一公式：pnl = position_value * pnl_percentage / 100
            # pnl_percentage > 0 = 盈利, pnl_percentage < 0 = 亏损
            pnl = position_value * pnl_percentage / 100
            
            hold_seconds = random.randint(60, 3600)
            
            entry_time = datetime.now() - timedelta(seconds=hold_seconds)

            demo_state["total_trades"] += 1
            if is_win:
                demo_state["winning_trades"] += 1
            else:
                demo_state["losing_trades"] += 1

            demo_state["total_pnl"] += pnl
            demo_state["daily_pnl"] += pnl
            demo_state["current_capital"] = demo_state["initial_capital"] + demo_state["total_pnl"]

            trade = {
                "symbol": symbol,
                "side": side,
                "entry_price": round(entry_price, 2),
                "exit_price": round(exit_price, 2),
                "quantity": round(quantity, 4),
                "leverage": leverage,
                "position_value": round(position_value, 2),
                "pnl": round(pnl, 2),
                "pnl_percentage": round(pnl_percentage, 2),
                "commission": round(position_value * 0.001, 2),
                "strategy": demo_state["selected_strategy"],
                "entry_time": entry_time.isoformat(),
                "exit_time": datetime.now().isoformat(),
                "hold_duration_seconds": hold_seconds,
                # 开仓条件
                "entry_conditions": {
                    "rsi": round(random.uniform(30, 70), 1),
                    "volume_ratio": round(random.uniform(1.5, 4.0), 2),
                    "atr": round(random.uniform(0.5, 2.0), 2),
                    "trend": random.choice(["UP", "DOWN"]),
                    "breakout": random.choice([True, False]),
                    "signal_confidence": round(random.uniform(0.65, 0.95), 2)
                }
            }

            demo_state["recent_trades"].append(trade)
            if len(demo_state["recent_trades"]) > 20:
                demo_state["recent_trades"] = demo_state["recent_trades"][-20:]

            logger.info(f"Simulated trade: {trade['side']} {symbol} ${pnl:.2f}")

        # Simulate position changes
        if random.random() < 0.2 and len(demo_state["open_positions"]) < 2:
            # Open position
            symbol = random.choice(symbols)
            if symbol == "BTCUSDT":
                base_price = random.uniform(42000, 45000)
            elif symbol == "ETHUSDT":
                base_price = random.uniform(2800, 3200)
            else:
                base_price = random.uniform(95, 110)
            
            side = random.choice(["LONG", "SHORT"])
            leverage = random.choice([5, 10, 15, 20])
            quantity = random.uniform(0.01, 0.1)
            
            # Position value = 数量 × 价格（不是乘以杠杆，杠杆只是影响保证金和盈亏）
            position_value = base_price * quantity
            
            pos = {
                "symbol": symbol,
                "side": side,
                "entry_price": round(base_price, 2),
                "current_price": round(base_price * random.uniform(0.99, 1.01), 2),
                "quantity": round(quantity, 4),
                "leverage": leverage,
                "position_value": round(position_value, 2),
                "unrealized_pnl": 0,
                "stop_loss": 0,
                "take_profit": 0,
                "liquidation_price": 0,
                "strategy": demo_state["selected_strategy"],
                "entry_time": datetime.now().isoformat()
            }
            
            # 计算未实现盈亏（不乘杠杆）
            # PnL = (当前价 - 入场价) × 数量
            pnl_per_unit = quantity
            if side == "LONG":
                pos["unrealized_pnl"] = round((pos["current_price"] - pos["entry_price"]) * pnl_per_unit, 2)
            else:
                pos["unrealized_pnl"] = round((pos["entry_price"] - pos["current_price"]) * pnl_per_unit, 2)
            
            # 设置止损止盈（方向正确）
            if side == "LONG":
                # 多单：止损在入场价下方，止盈在入场价上方
                pos["stop_loss"] = round(pos["entry_price"] * (1 - 0.02), 2)  # 2% 止损
                pos["take_profit"] = round(pos["entry_price"] * (1 + 0.04), 2)  # 4% 止盈
            else:
                # 空单：止损在入场价上方，止盈在入场价下方
                pos["stop_loss"] = round(pos["entry_price"] * (1 + 0.02), 2)  # 2% 止损
                pos["take_profit"] = round(pos["entry_price"] * (1 - 0.04), 2)  # 4% 止盈
            
            # 清算价格计算
            liq_distance = 1 / leverage
            if side == "LONG":
                pos["liquidation_price"] = round(pos["entry_price"] * (1 - liq_distance + 0.01), 2)
            else:
                pos["liquidation_price"] = round(pos["entry_price"] * (1 + liq_distance - 0.01), 2)

            demo_state["open_positions"].append(pos)
            logger.info(f"Opened position: {pos['side']} {pos['symbol']} @ {pos['entry_price']}")

        elif demo_state["open_positions"] and random.random() < 0.3:
            # Close position
            demo_state["open_positions"].pop(0)
            logger.info("Closed position")

        # Update existing positions
        for pos in demo_state["open_positions"]:
            price_change = random.uniform(0.998, 1.002)
            pos["current_price"] = pos["current_price"] * price_change
            
            # 不乘杠杆
            if pos["side"] == "LONG":
                pos["unrealized_pnl"] = round((pos["current_price"] - pos["entry_price"]) * pos["quantity"], 2)
            else:
                pos["unrealized_pnl"] = round((pos["entry_price"] - pos["current_price"]) * pos["quantity"], 2)


def verify_token(request: Request):
    """Verify session token"""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:]
    expiry = sessions.get(token)
    if expiry and expiry > datetime.now():
        return token
    return None


@app.post("/api/login")
async def login(request: Request):
    """登录端点 - 支持密码登录和飞书登录"""
    try:
        data = await request.json()
        login_type = data.get("type", "password")
        
        if login_type == "feishu":
            # 飞书扫码登录
            code = data.get("code")
            state = data.get("state")
            
            if not FEISHU_ENABLED:
                return {"success": False, "message": "Feishu login not available", "type": "feishu"}
            
            session_token = verify_auth_code(code, state)
            if session_token:
                # 存储session
                sessions[session_token] = datetime.now() + timedelta(days=7)
                return {
                    "success": True, 
                    "token": session_token, 
                    "type": "feishu",
                    "message": "Login successful"
                }
            else:
                return {"success": False, "message": "Invalid code or expired", "type": "feishu"}
        
        else:
            # 密码登录（备用）
            username = data.get("username")
            password = data.get("password")
            
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            
            if username == "admin" and password_hash == "2b558bcd816cc30918215b8cf4ce026d9a2da0cc82414af105a9e0f1303e7626":  # [:WDy$W*D-RzTQ%
                token = secrets.token_hex(32)
                sessions[token] = datetime.now() + timedelta(hours=24)
                return {"success": True, "token": token, "type": "password"}
            else:
                return {"success": False, "message": "Invalid credentials", "type": "password"}
                
    except Exception as e:
        return {"success": False, "message": str(e)}


@app.get("/api/login/qr")
async def get_login_qr():
    """获取飞书登录二维码"""
    if not FEISHU_ENABLED:
        return {"success": False, "message": "Feishu login not available"}
    
    try:
        qr_data = generate_login_qr()
        return {
            "success": True,
            "type": "feishu",
            "qrcode_url": qr_data.get("qrcode_url"),
            "login_page_url": qr_data.get("login_page_url") or qr_data.get("auth_url"),
            "auth_url": qr_data.get("auth_url"),
            "state": qr_data.get("state"),
            "expires_in": qr_data.get("expires_in")
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


@app.get("/auth/lark/callback")
async def lark_callback(request: Request):
    """Lark授权回调"""
    logger.info(f"Lark callback received: {request.query_params}")
    
    if not FEISHU_ENABLED:
        logger.error("FEISHU_ENABLED is False")
        return JSONResponse({"success": False, "message": "Feishu not enabled"})
    
    try:
        code = request.query_params.get("code")
        state = request.query_params.get("state")
        
        if not code:
            return JSONResponse({"success": False, "message": "No code provided"})
        
        logger.info(f"Exchanging code: {code[:10]}...")
        session_token = verify_auth_code(code, state)
        
        if session_token:
            sessions[session_token] = datetime.now() + timedelta(days=7)
            logger.info(f"Session created: {session_token[:10]}..., sessions count: {len(sessions)}")
            # 重定向回首页
            response = RedirectResponse(url="/?token=" + session_token)
            response.set_cookie(key="authToken", value=session_token, httponly=True, max_age=60*60*24*7)
            return response
        else:
            logger.error("Failed to verify auth code")
            return {"success": False, "message": "Invalid code"}
            
    except Exception as e:
        logger.error(f"Lark callback error: {e}")
        return {"success": False, "message": str(e)}


@app.post("/auth/lark/callback")
async def feishu_callback_post(request: Request):
    """飞书授权回调 - POST请求"""
    return await feishu_callback(request)


@app.get("/api/login/status")
async def get_login_status():
    """获取登录状态信息"""
    return {
        "feishu_enabled": FEISHU_ENABLED,
        "login_methods": ["feishu"] if FEISHU_ENABLED else ["password"]
    }


@app.post("/api/logout")
async def logout(request: Request):
    """Logout endpoint"""
    token = verify_token(request)
    if token and token in sessions:
        del sessions[token]
    return {"success": True}


@app.get("/")
async def root():
    """Serve dashboard"""
    dashboard_path = os.path.join(os.path.dirname(__file__), 'dashboard.html')
    if os.path.exists(dashboard_path):
        return FileResponse(dashboard_path)
    return {"message": "Dashboard not found"}


@app.get("/dashboard/summary")
async def get_dashboard_summary(request: Request):
    """Get dashboard data - requires authentication"""
    # Check authentication
    token = verify_token(request)
    if not token:
        return JSONResponse(
            status_code=401,
            content={"error": "Unauthorized"}
        )

    win_rate = (demo_state["winning_trades"] / demo_state["total_trades"] * 100) if demo_state["total_trades"] > 0 else 0
    roi = (demo_state["total_pnl"] / demo_state["initial_capital"] * 100) if demo_state["initial_capital"] > 0 else 0
    
    # Calculate unrealized PnL from open positions
    unrealized_pnl = sum(pos.get("unrealized_pnl", 0) for pos in demo_state["open_positions"])

    return {
        "timestamp": datetime.now().isoformat(),
        "bot_status": {
            "running": demo_state["running"],
            "symbols": ["BTCUSDT", "ETHUSDT"],
            "dynamic_selector": True
        },
        "statistics": {
            "initial_capital": demo_state["initial_capital"],
            "current_capital": demo_state["current_capital"],
            "total_pnl": demo_state["total_pnl"],
            "unrealized_pnl": unrealized_pnl,
            "roi": roi,
            "win_rate": win_rate,
            "total_trades": demo_state["total_trades"],
            "winning_trades": demo_state["winning_trades"],
            "losing_trades": demo_state["losing_trades"],
            "open_positions": len(demo_state["open_positions"]),
            "daily_pnl": demo_state["daily_pnl"],
            "max_drawdown": -5.2
        },
        "regime_info": {
            "current_regime": demo_state["current_regime"],
            "confidence": demo_state["regime_confidence"],
            "selected_strategy": demo_state["selected_strategy"],
            "regime_distribution": {
                "high_vol_trending": 45,
                "low_vol_ranging": 30,
                "momentum_exhaustion": 15,
                "mixed": 10
            },
            "strategy_performance": demo_state["strategy_stats"]
        },
        "open_positions": demo_state["open_positions"],
        "recent_trades": demo_state["recent_trades"]
    }


@app.get("/dashboard/closed-positions")
async def get_closed_positions(request: Request, limit: int = 200):
    """Get closed positions"""
    token = verify_token(request)
    if not token:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    
    trades = demo_state["recent_trades"][:limit]
    # 转换为前端期望的格式（不乘杠杆）
    closed_positions = []
    for trade in trades:
        entry_price = trade.get("entry_price", 0)
        quantity = trade.get("quantity", 0)
        pnl = trade.get("pnl", 0)
        
        # Position Value = 价格 × 数量（不乘杠杆）
        position_value = entry_price * quantity
        # PnL % = PnL / Position Value × 100
        pnl_percentage = (pnl / position_value * 100) if position_value > 0 else 0
        
        closed_positions.append({
            "symbol": trade.get("symbol", "BTCUSDT"),
            "side": "BUY" if trade.get("side") == "LONG" else "SELL",
            "price": entry_price,
            "quantity": quantity,
            "realized_pnl": pnl,
            "pnl_percentage": round(pnl_percentage, 2),
            "time": trade.get("exit_time", trade.get("entry_time", "")),
            "commission": trade.get("commission", 0)
        })
    
    return {"closed_positions": closed_positions, "count": len(closed_positions)}


def main():
    """Main entry point"""
    print("="*70)
    print("ASTER Trading Bot - DEMO MODE")
    print("="*70)
    print("\nDashboard starting...")
    print("\nThis is a DEMO with simulated data")
    print("   No real trading or exchange connection")
    print("   Just to show you how the dashboard looks!\n")

    # Start market simulator in background
    simulator_thread = threading.Thread(target=simulate_market_updates, daemon=True)
    simulator_thread.start()

    # Add some initial trades
    for i in range(5):
        side = random.choice(["LONG", "SHORT"])
        is_win = random.random() < 0.6
        
        if is_win:
            pnl_percentage = random.uniform(1, 5)
        else:
            pnl_percentage = random.uniform(-5, -1)
        
        entry_price = round(random.uniform(48000, 52000), 2)
        quantity = round(random.uniform(0.01, 0.05), 4)
        position_value = entry_price * quantity
        pnl = position_value * pnl_percentage / 100
        
        # 根据多空方向计算出场价格
        if side == "LONG":
            exit_price = round(entry_price * (1 + pnl_percentage / 100), 2)
        else:
            exit_price = round(entry_price * (1 - pnl_percentage / 100), 2)

        demo_state["total_trades"] += 1
        if is_win:
            demo_state["winning_trades"] += 1
        else:
            demo_state["losing_trades"] += 1

        demo_state["total_pnl"] += pnl
        demo_state["daily_pnl"] += pnl

        trade = {
            "symbol": "BTCUSDT",
            "side": side,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "quantity": quantity,
            "pnl": round(pnl, 2),
        }
        trade["position_value"] = trade["entry_price"] * trade["quantity"]
        trade["pnl_percentage"] = round((trade["pnl"] / trade["position_value"] * 100) if trade["position_value"] > 0 else 0, 2)
        trade["exit_price"] = round(trade["entry_price"] * (1 + trade["pnl_percentage"]/100), 2)
        trade["strategy"] = random.choice(["Breakout Scalping", "Momentum Reversal", "Market Making"])
        trade["entry_time"] = datetime.now().isoformat()
        trade["exit_time"] = datetime.now().isoformat()
        trade["commission"] = round(trade["position_value"] * 0.001, 2)
        demo_state["recent_trades"].append(trade)

    demo_state["current_capital"] = demo_state["initial_capital"] + demo_state["total_pnl"]

    print("="*70)
    print("DASHBOARD READY!")
    print("="*70)
    print("\nOpen in browser:")
    print(f"   http://localhost:8000/")
    print("\nFrom phone (same WiFi):")
    print(f"   http://<YOUR_LOCAL_IP>:8000/")
    print("\nTo find your local IP:")
    print("   Run: ipconfig (look for IPv4 Address)")
    print("\nThe dashboard will auto-refresh every 10 seconds")
    print("   You'll see simulated trades appearing!\n")
    print("="*70)
    print("\nPress Ctrl+C to stop\n")

    # Start API server
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
