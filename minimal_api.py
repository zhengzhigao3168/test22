#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
极简版API服务

用于测试FastAPI是否能正常工作。
"""

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

# 创建FastAPI应用
app = FastAPI(
    title="极简版API服务",
    description="用于测试FastAPI是否能正常工作",
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

# 确保前端构建目录存在
os.makedirs("frontend/dist", exist_ok=True)

# 如果不存在index.html，则创建一个简单的
if not os.path.exists("frontend/dist/index.html"):
    with open("frontend/dist/index.html", "w", encoding="utf-8") as f:
        f.write("""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>极简版API测试</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; }
        .container { max-width: 800px; margin: 0 auto; }
    </style>
</head>
<body>
    <div class="container">
        <h1>极简版API测试</h1>
        <p>API状态: <span id="status">检查中...</span></p>
        <button onclick="checkAPI()">检查API状态</button>
    </div>
    <script>
        function checkAPI() {
            fetch('/api/status')
                .then(response => response.json())
                .then(data => {
                    document.getElementById('status').textContent = '正常运行';
                    console.log(data);
                })
                .catch(error => {
                    document.getElementById('status').textContent = '连接失败';
                    console.error(error);
                });
        }
        
        // 页面加载时自动检查
        window.onload = checkAPI;
    </script>
</body>
</html>
        """)

@app.get("/")
async def root():
    """API根路由"""
    return {"message": "极简版API服务正在运行"}

@app.get("/api/status")
async def get_status():
    """获取系统状态"""
    return {
        "status": "running",
        "message": "极简版API服务正常运行",
        "timestamp": "2024-05-28T12:00:00"
    }

# 挂载静态文件
app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="static")

if __name__ == "__main__":
    print("启动极简版API服务...")
    uvicorn.run(app, host="0.0.0.0", port=9999) 