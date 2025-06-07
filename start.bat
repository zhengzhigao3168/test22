@echo off
echo 正在启动图片采集程序...
echo 请确保已安装Python环境和所需依赖

REM 检查是否已安装依赖
pip install -r requirements.txt

REM 启动主程序
python "edotfish图像处理升级版.py"

pause