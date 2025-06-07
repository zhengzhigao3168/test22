#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
独立的临时API服务器，不依赖于任何现有代码
"""

import os
import sys
import logging
from datetime import datetime
import uvicorn
from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("standalone_api")

# 创建FastAPI应用
app = FastAPI(
    title="AI市场分析系统API",
    description="临时独立版API系统",
    version="1.0.0"
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 创建API路由器
api_router = APIRouter()

@api_router.get("/")
async def root():
    """API根路由"""
    return {"message": "AI市场分析系统API服务正在运行 (临时独立版)"}

@api_router.get("/status")
async def get_status():
    """获取系统状态"""
    return {
        "status": "running",
        "version": "1.0.0 (临时独立版)",
        "message": "独立版后端服务器已成功启动",
        "timestamp": datetime.now().isoformat()
    }

@api_router.get("/market/sentiment")
async def get_market_sentiment():
    """获取市场情绪 (模拟数据)"""
    return {
        "overall_sentiment": 0.55,
        "retail_sentiment": 0.60,
        "institutional_sentiment": 0.50,
        "market_trend": "震荡上行",
        "sentiment_change": 0.05,
        "hot_sectors": [
            {"name": "新能源", "sentiment": 0.75},
            {"name": "半导体", "sentiment": 0.70},
            {"name": "消费", "sentiment": 0.50},
            {"name": "医药", "sentiment": 0.45}
        ],
        "timestamp": datetime.now().isoformat(),
        "is_real_data": False,
        "greed_fear_index": 55,
        "market_mood": "谨慎乐观",
        "strategy_advice": "市场情绪偏向乐观，但建议保持谨慎，逢高减仓"
    }

@api_router.get("/signals/latest")
async def get_latest_signals():
    """获取最新交易信号 (模拟数据)"""
    return {
        "stock_code": "000001.SZ",
        "signals": {
            "technical": {
                "type": "buy",
                "score": 0.75,
                "indicators": {
                    "rsi": 28.5,
                    "macd": "上穿",
                    "ma": "多头排列"
                },
                "timestamp": datetime.now().isoformat()
            },
            "main_force": {
                "type": "buy",
                "score": 0.68,
                "fund_flow": 15600000,
                "big_orders": 12,
                "timestamp": datetime.now().isoformat()
            }
        },
        "timestamp": datetime.now().isoformat()
    }

# 添加API路由
app.include_router(api_router, prefix="/api")

# 如果存在静态文件目录，挂载它
frontend_dir = "frontend/dist"
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    logger.info(f"已挂载前端静态文件目录: {frontend_dir}")
else:
    logger.warning(f"前端静态文件目录不存在: {frontend_dir}")

# 主函数
def main():
    """启动独立API服务器"""
    print("启动临时独立版API服务器...")
    port = 8000
    print(f"服务器将运行在 http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main() 