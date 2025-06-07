#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
前端构建和运行脚本

用于构建React前端并启动开发服务器
"""

import os
import sys
import subprocess
import platform
import time

# 配置
FRONTEND_DIR = "frontend"
FRONTEND_PORT = 3000

def check_nodejs():
    """检查Node.js是否安装"""
    try:
        subprocess.check_output(["node", "--version"])
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("错误: 未安装Node.js或无法访问。请先安装Node.js。")
        return False

def install_dependencies():
    """安装前端依赖"""
    print("安装前端依赖...")
    os.chdir(FRONTEND_DIR)
    
    try:
        subprocess.check_call(["npm", "install"])
        print("依赖安装完成")
        return True
    except subprocess.CalledProcessError as e:
        print(f"安装依赖失败: {str(e)}")
        return False
    finally:
        os.chdir("..")

def build_frontend():
    """构建前端生产版本"""
    print("构建前端...")
    os.chdir(FRONTEND_DIR)
    
    try:
        subprocess.check_call(["npm", "run", "build"])
        print("前端构建完成")
        return True
    except subprocess.CalledProcessError as e:
        print(f"构建失败: {str(e)}")
        return False
    finally:
        os.chdir("..")

def start_dev_server():
    """启动开发服务器"""
    print(f"启动前端开发服务器，端口 {FRONTEND_PORT}...")
    os.chdir(FRONTEND_DIR)
    
    try:
        process = subprocess.Popen(["npm", "start"])
        print(f"前端开发服务器已启动，访问 http://localhost:{FRONTEND_PORT}")
        return process
    except subprocess.CalledProcessError as e:
        print(f"启动开发服务器失败: {str(e)}")
        return None
    finally:
        os.chdir("..")

def main():
    """主函数"""
    if not check_nodejs():
        sys.exit(1)
    
    print("=== React前端构建与运行工具 ===")
    print("1. 安装依赖")
    print("2. 构建生产版本")
    print("3. 启动开发服务器")
    print("4. 全部执行（安装、构建、启动）")
    print("0. 退出")
    
    choice = input("请选择操作: ")
    
    if choice == "1":
        install_dependencies()
    elif choice == "2":
        build_frontend()
    elif choice == "3":
        dev_process = start_dev_server()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n停止开发服务器...")
            if dev_process:
                dev_process.terminate()
    elif choice == "4":
        if install_dependencies():
            if build_frontend():
                dev_process = start_dev_server()
                try:
                    while True:
                        time.sleep(1)
                except KeyboardInterrupt:
                    print("\n停止开发服务器...")
                    if dev_process:
                        dev_process.terminate()
    elif choice == "0":
        print("退出")
    else:
        print("无效选择")

if __name__ == "__main__":
    main() 