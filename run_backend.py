#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
后端启动脚本 - 直接使用React前端

此脚本用于启动AI市场分析系统的后端API服务。
"""

import os
import sys
import time
import subprocess
import signal
import platform

# 配置
API_PORT = 8000  # 后端API端口
API_PROCESS = None

def kill_process_on_port(port):
    """杀死占用指定端口的进程"""
    print(f"尝试关闭端口 {port} 上的进程...")
    
    if platform.system() == "Windows":
        # Windows系统使用netstat和taskkill
        try:
            # 查找占用端口的进程PID
            cmd = f'netstat -ano | findstr ":{port}"'
            result = subprocess.check_output(cmd, shell=True).decode('utf-8')
            
            if result:
                # 提取PID
                pids = set()
                for line in result.strip().split('\n'):
                    if f":{port}" in line and "LISTENING" in line:
                        parts = line.strip().split()
                        if len(parts) >= 5:
                            pid = parts[-1]
                            # 确保PID是有效的数字且不是0
                            if pid.isdigit() and int(pid) > 0:
                                pids.add(pid)
                
                if pids:
                    for pid in pids:
                        try:
                            # 杀死进程
                            kill_cmd = f'taskkill /F /PID {pid}'
                            subprocess.check_output(kill_cmd, shell=True)
                            print(f"已终止占用端口 {port} 的进程 (PID: {pid})")
                        except subprocess.CalledProcessError as e:
                            print(f"无法终止进程 {pid}: {str(e)}")
                else:
                    print(f"未找到占用端口 {port} 的有效进程")
            else:
                print(f"端口 {port} 没有被占用")
        except subprocess.CalledProcessError:
            print(f"端口 {port} 没有被占用或无法获取进程信息")
    else:
        # Linux/Mac系统使用lsof和kill
        try:
            # 查找占用端口的进程PID
            cmd = f"lsof -i:{port} -t"
            output = subprocess.check_output(cmd, shell=True).decode('utf-8').strip()
            
            if output:
                pids = output.split('\n')
                for pid in pids:
                    if pid.isdigit() and int(pid) > 0:
                        try:
                            # 杀死进程
                            os.kill(int(pid), signal.SIGKILL)
                            print(f"已终止占用端口 {port} 的进程 (PID: {pid})")
                        except OSError as e:
                            print(f"无法终止进程 {pid}: {str(e)}")
            else:
                print(f"端口 {port} 没有被占用")
        except subprocess.CalledProcessError:
            print(f"端口 {port} 没有被占用或无法获取进程信息")

def kill_process_by_name(process_name):
    """根据进程名称杀死进程"""
    print(f"尝试关闭 {process_name} 进程...")
    
    if platform.system() == "Windows":
        try:
            kill_cmd = f'taskkill /F /IM {process_name}'
            subprocess.check_output(kill_cmd, shell=True)
            print(f"已终止 {process_name} 进程")
            return True
        except subprocess.CalledProcessError:
            print(f"未找到 {process_name} 进程或无法终止")
            return False
    else:
        try:
            cmd = f"pkill -9 {process_name}"
            subprocess.check_output(cmd, shell=True)
            print(f"已终止 {process_name} 进程")
            return True
        except subprocess.CalledProcessError:
            print(f"未找到 {process_name} 进程或无法终止")
            return False

def start_backend():
    """启动后端API服务"""
    global API_PROCESS
    
    print("启动后端API服务...")
    
    # 确保当前目录在系统路径中
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)
    
    # 使用subprocess启动临时简化版后端服务
    if platform.system() == "Windows":
        API_PROCESS = subprocess.Popen(
            ["python", "run_backend_simple.py"]
        )
    else:
        API_PROCESS = subprocess.Popen(
            ["python3", "run_backend_simple.py"]
        )
    
    print(f"后端API服务已启动，运行在 http://localhost:{API_PORT}")

def cleanup():
    """清理资源并终止进程"""
    global API_PROCESS
    
    print("\n正在关闭服务...")
    
    # 终止后端进程
    if API_PROCESS:
        API_PROCESS.terminate()
        API_PROCESS.wait()
        print("后端API服务已关闭")

def main():
    """主函数"""
    try:
        print("\n=== 启动AI市场分析系统 (临时简化版) ===")
        
        # 先尝试通过进程名关闭可能存在的服务
        kill_process_by_name("uvicorn.exe")
        
        # 关闭可能占用的端口
        kill_process_on_port(API_PORT)
        
        # 等待端口完全释放
        time.sleep(1)
        
        # 启动后端服务
        start_backend()
        
        print("\n系统已启动完成!")
        print(f"请访问 http://localhost:{API_PORT} 使用系统")
        print("按 Ctrl+C 停止服务")
        
        # 保持脚本运行
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n接收到停止信号")
    finally:
        cleanup()

if __name__ == "__main__":
    main() 