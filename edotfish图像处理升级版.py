import requests
import os
import json
from datetime import datetime
import time
import threading
from PIL import Image
import urllib.parse
import sys
import re # 添加 re 模块导入
import random

# 检查是否已安装Playwright
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
    print("已检测到 Playwright 库。")
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("警告: Playwright 库未安装。亚马逊商品信息抓取功能将不可用。")
    print("您可以手动安装 Playwright: pip install playwright")
    print("然后安装浏览器驱动: playwright install")

# 旧版模拟逻辑保留，但只在PLAYWRIGHT_AVAILABLE为False时使用
if not PLAYWRIGHT_AVAILABLE and 'default_api' not in globals():
    print("警告: 'default_api' 未在全局作用域中定义，并且 Playwright 库未安装。")
    print("自动抓取亚马逊商品信息将不可用。")
    class MockDefaultAPI:
        def __init__(self):
            self.has_warned_navigate = False
            self.has_warned_wait = False
            self.has_warned_snapshot = False

        def mcp_playwright_browser_navigate(self, url):
            if not self.has_warned_navigate:
                print(f"模拟MCP调用: navigating to {url} (此为模拟，无实际浏览器操作)")
                self.has_warned_navigate = True
            return {"status": "success_mocked_navigation"}

        def mcp_playwright_browser_wait_for(self, time):
            if not self.has_warned_wait:
                print(f"模拟MCP调用: waiting for {time} seconds (此为模拟)")
                self.has_warned_wait = True
            return {"status": "success_mocked_wait"}

        def mcp_playwright_browser_snapshot(self, random_string):
            if not self.has_warned_snapshot:
                print(f"模拟MCP调用: taking snapshot with ID {random_string} (此为模拟，返回空快照结构)")
                self.has_warned_snapshot = True
            return {
                "result": {
                    "snapshot": {
                        "role": "document", 
                        "name": "模拟快照 - 无真实网页数据", 
                        "children": [],
                        "attributes": {} 
                    }
                },
                "status": "success_mocked_snapshot"
            }
    default_api = MockDefaultAPI()

# 尝试导入 Pillow 库
# try:
#     from PIL import Image
#     PIL_AVAILABLE = True
# except ImportError:
#     PIL_AVAILABLE = False
#     print("警告: Pillow 库未安装。PNG透明区域自动生成蒙版功能将不可用。")
#     print("您可以手动安装 Pillow: pip install Pillow")
PIL_AVAILABLE = True

YUNWU_BASE_URL = "https://yunwu.ai/ideogram" # 云雾API的基础URL，需要确认是否包含 /v1 或其他路径
RESOURCES_FOLDER = "素材"
OUTPUT_FOLDER = "成品"

# --- API 端点映射 (基于云雾API文档) ---
# key: 用户友好的功能名称
# value: dict containing 'endpoint_suffix' and 'required_params' (and 'optional_params')
# required_params is a list of param names. For file type, it's just 'image'.
# For other text params, it will be like 'prompt', 'resolution' etc.
# optional_params is also a list.
IDEOGRAM_FUNCTIONS_YUNWU = {
    "抠图去背景 (Make Background Transparent)": { # 新增功能
        "endpoint_suffix": "/v1/ideogram-v3/replace-background", # 复用替换背景的API
        "method": "POST",
        "required_params": ["image"], # 用户只需要提供图片
        "optional_params": ["resolution"], # 分辨率可选
        "fixed_params": {"prompt": "", "num_images": 1}, # 修改点：尝试使用空prompt
        "description": "将图片背景变透明，突出主体。 (尝试通过空prompt触发)",
        "official_doc": "https://developer.ideogram.ai/api-reference/api-reference/replace-background-v3" # 与替换背景相同
    },
    "图片重构 (Reframe V3)": {
        "endpoint_suffix": "/v1/ideogram-v3/reframe",
        "method": "POST",
        "required_params": ["image"],
        "optional_params": ["resolution"],
        "description": "根据AI推断扩展图像边界，类似智能填充。不需要额外提示词。",
        "official_doc": "https://developer.ideogram.ai/api-reference/api-reference/reframe-v3"
    },
    "替换背景 (Replace Background V3)": {
        "endpoint_suffix": "/v1/ideogram-v3/replace-background",
        "method": "POST",
        "required_params": ["image", "prompt"],
        "optional_params": ["resolution", "num_images"],
        "description": "根据提示词替换图像背景。",
        "official_doc": "https://developer.ideogram.ai/api-reference/api-reference/replace-background-v3"
    },
    "文生图 (Generate V3)": {
        "endpoint_suffix": "/v1/ideogram-v3/generate",
        "method": "POST",
        "required_params": ["prompt"],
        "optional_params": [
            "aspect_ratio", "resolution", "model_version", "rendering_speed", 
            "magic_prompt", "negative_prompt", "num_images", "seed", 
            "style_codes", "style_type", "style_reference_images" 
            # color_palette 是一个对象，处理起来较复杂，暂时简化
        ],
        "description": "根据文本提示生成图像。",
        "official_doc": "https://developer.ideogram.ai/api-reference/api-reference/generate-v3"
    },
    "图片编辑 (Edit V3)": {
        "endpoint_suffix": "/v1/ideogram-v3/edit",
        "method": "POST",
        "required_params": ["image", "prompt"],
        "optional_params": [
            "aspect_ratio", "resolution", "model_version", "rendering_speed", 
            "magic_prompt", "negative_prompt", "seed", 
            "style_codes", "style_type", "style_reference_images",
            "edit_area", # edit_strength 已移除
            "mask"
        ],
        "description": "根据提示词编辑现有图像的特定区域或整体。",
        "official_doc": "https://developer.ideogram.ai/api-reference/api-reference/edit-v3"
    },
    "图片重制 (Remix V3)": {
        "endpoint_suffix": "/v1/ideogram-v3/remix",
        "method": "POST",
        "required_params": ["image", "prompt"],
        "optional_params": [
            "aspect_ratio", "resolution", "model_version", "rendering_speed",
            "magic_prompt", "negative_prompt", "seed", "image_weight",
            "style_codes", "style_type", "style_reference_images"
            # color_palette
        ],
        "description": "基于输入图像和提示词重新混合生成新图像。",
        "official_doc": "https://developer.ideogram.ai/api-reference/api-reference/remix-v3"
    },
    "放大高清 (Upscale)": {
        "endpoint_suffix": "/upscale", 
        "method": "POST",
        "required_params": ["image_file"], 
        "optional_params": ["resemblance", "detail", "upscale_prompt", "magic_prompt_option", "seed"], 
        "description": "放大图像并提升细节 (最高2倍)。可提供相似度、细节(1-100)、辅助提示、魔法提示选项、种子。",
        "official_doc": "https://developer.ideogram.ai/api-reference/api-reference/upscale"
    },
    "图像描述 (Describe)": {
        "endpoint_suffix": "/describe", # 基于用户提供的 http.client 范例更新
        "method": "POST",
        "required_params": ["image_file"], # 基于用户提供的 http.client 范例更新参数名
        "optional_params": [],
        "description": "为输入图像生成文本描述。)",
        "official_doc": "https://developer.ideogram.ai/api-reference/api-reference/describe"
    }
    # 可以根据云雾API文档继续添加其他旧版API或更多功能
}

# --- 新增：特定组合功能名称 ---
DESCRIBE_AND_FILL_BACKGROUND_FUNC_NAME = "智能背景填充 (Describe JPG + Fill PNG Background)"
DESCRIBE_AND_REMIX_IMAGE_FUNC_NAME = "智能图片重制 (Describe JPG + Remix PNG)"
DESCRIBE_AND_EDIT_IMAGE_FUNC_NAME = "智能图片编辑 (Describe JPG + Edit PNG)" # 新增组合功能名

def create_folders():
    """创建素材和成品文件夹 (如果不存在)。"""
    os.makedirs(RESOURCES_FOLDER, exist_ok=True)
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
 

def get_api_key():
    """从用户处获取云雾 API Key。"""
    # api_key = input("请输入您的云雾 API Key: ").strip()
    # if not api_key:
    #     print("API Key 不能为空。程序退出。")
    #     exit()
    # return api_key
    return "sk-91T6x89mHpe72h1dr4RoKxiSyBHzpJJvoAQcq9l3GLsrJyTX" # 直接使用您提供的API Key

def display_and_select_function(api_key):
    """显示可用功能并让用户选择。"""
    
    # 定义要从主列表移除的选项名称
    functions_to_remove_from_direct_listing = [
        "图片重构 (Reframe V3)",
        "替换背景 (Replace Background V3)", # 我们的组合功能会用，但此处不直接列出
        "图片编辑 (Edit V3)",           # 我们的组合功能会用
        "图片重制 (Remix V3)",            # 我们的组合功能会用
        "文生图 (Generate V3)"          # 将文生图从直接列表移除
    ]
    
    # 构建实际显示给用户的列表
    displayable_functions = []
    for func_name in IDEOGRAM_FUNCTIONS_YUNWU.keys():
        if func_name not in functions_to_remove_from_direct_listing:
            displayable_functions.append(func_name)

    for i, func_name in enumerate(displayable_functions):
        details = IDEOGRAM_FUNCTIONS_YUNWU[func_name]
        # 移除括号及其内容
        cleaned_func_name = func_name.split(" (")[0]
        print(f"{i+1}. {cleaned_func_name} - {details.get('description', '无描述')}")

    # --- 组合功能列表保持不变，但其序号会基于 displayable_functions 的长度 ---
    num_displayable_direct_funcs = len(displayable_functions)
    
    # 清理组合功能名称的显示
    cleaned_fill_name = DESCRIBE_AND_FILL_BACKGROUND_FUNC_NAME.split(" (")[0]
    cleaned_remix_name = DESCRIBE_AND_REMIX_IMAGE_FUNC_NAME.split(" (")[0]
    cleaned_edit_name = DESCRIBE_AND_EDIT_IMAGE_FUNC_NAME.split(" (")[0]

    print(f"{num_displayable_direct_funcs + 1}. {cleaned_fill_name} - 使用JPG生成描述，再填充PNG背景。")
    print(f"{num_displayable_direct_funcs + 2}. {cleaned_remix_name} - 使用JPG生成描述，再重制PNG图像。") 
    print(f"{num_displayable_direct_funcs + 3}. {cleaned_edit_name} - 使用JPG生成描述，再编辑PNG图像(整体编辑)。")
    print(f"{num_displayable_direct_funcs + 4}. 亚马逊采集 - 从亚马逊商品页面采集信息和图片。")
    print(f"{num_displayable_direct_funcs + 5}. 阿里巴巴采集 - 从阿里巴巴商品页面采集信息和图片。")

    while True:
        try:
            choice_input = int(input("请选择要使用的功能序号: ")) - 1
            # 判断用户选择的是直接功能还是组合功能
            if 0 <= choice_input < num_displayable_direct_funcs:
                selected_func_name = displayable_functions[choice_input]
                print(f"您选择了: {selected_func_name}")
                process_selected_function(api_key, selected_func_name, IDEOGRAM_FUNCTIONS_YUNWU[selected_func_name])
                break
            elif choice_input == num_displayable_direct_funcs: # 用户选择了 "智能背景填充"
                print(f"您选择了: {DESCRIBE_AND_FILL_BACKGROUND_FUNC_NAME}")
                process_describe_and_fill_background(api_key)
                break
            elif choice_input == num_displayable_direct_funcs + 1: # 用户选择了 "智能图片重制"
                print(f"您选择了: {DESCRIBE_AND_REMIX_IMAGE_FUNC_NAME}")
                process_describe_and_remix_image(api_key)
                break
            elif choice_input == num_displayable_direct_funcs + 2: # 用户选择了 "智能图片编辑"
                print(f"您选择了: {DESCRIBE_AND_EDIT_IMAGE_FUNC_NAME}")
                process_describe_and_edit_image(api_key)
                break
            elif choice_input == num_displayable_direct_funcs + 3: # 用户选择了 "亚马逊采集"
                print("您选择了: 亚马逊采集")
                get_amazon_product_info_and_generate_prompt_for_edit(api_key)
                break
            elif choice_input == num_displayable_direct_funcs + 4: # 用户选择了 "阿里巴巴采集"
                print("您选择了: 阿里巴巴采集")
                get_alibaba_product_info_and_generate_prompt_for_edit(api_key)
                break
            else:
                print("无效的选择，请输入列表中的序号。")
        except ValueError:
            print("请输入数字序号。")

def get_user_inputs_for_function(func_details):
    """根据功能需求获取用户输入。"""
    user_params = {}
    files_to_upload = {}

    print("\n--- 请输入所需参数 ---")
    for param_name in func_details.get("required_params", []):
        if param_name == "image" or "image" in param_name or param_name == "image_file": # 处理如 "image", "style_reference_images", "image_file"
            while True:
                if param_name == "style_reference_images":
                    img_paths_str = input(f"请输入风格参考图片文件名 (在 '{RESOURCES_FOLDER}' 文件夹中，多个用逗号分隔，可留空): ").strip()
                    if not img_paths_str:
                        break # 可选的，允许为空
                    img_filenames = [name.strip() for name in img_paths_str.split(',')]
                    valid_files = []
                    all_valid = True
                    for fname in img_filenames:
                        full_path = os.path.join(RESOURCES_FOLDER, fname)
                        if os.path.isfile(full_path):
                            valid_files.append(full_path)
                        else:
                            print(f"错误: 图片 '{fname}' 在 '{RESOURCES_FOLDER}' 中未找到。请重新输入。")
                            all_valid = False
                            break
                    if all_valid:
                        if valid_files: # 只有当确实有文件时才加入
                             files_to_upload[param_name] = valid_files # 存储为列表
                        break
                else: # 单个图片
                    img_filename = input(f"请输入图片文件名 (在 '{RESOURCES_FOLDER}' 文件夹中) for '{param_name}': ").strip()
                    full_path = os.path.join(RESOURCES_FOLDER, img_filename)
                    if os.path.isfile(full_path):
                        files_to_upload[param_name] = full_path # 存储单个路径
                        break
                    else:
                        print(f"错误: 图片 '{img_filename}' 在 '{RESOURCES_FOLDER}' 中未找到。请重试。")
        else:
            user_params[param_name] = input(f"请输入 '{param_name}': ").strip()

    for param_name in func_details.get("optional_params", []):
        # 对于可选文件参数，如 style_reference_images，如果上面已处理，则跳过
        if param_name == "style_reference_images" and param_name in files_to_upload:
            continue

        if "image" in param_name: # 例如 style_reference_images (如果之前未处理)
             while True:
                img_paths_str = input(f"请输入可选的风格参考图片文件名 (在 '{RESOURCES_FOLDER}' 中，多个用逗号分隔，可留空) for '{param_name}': ").strip()
                if not img_paths_str:
                    break 
                img_filenames = [name.strip() for name in img_paths_str.split(',')]
                valid_files = []
                all_valid = True
                for fname in img_filenames:
                    full_path = os.path.join(RESOURCES_FOLDER, fname)
                    if os.path.isfile(full_path):
                        valid_files.append(full_path)
                    else:
                        print(f"错误: 图片 '{fname}' 在 '{RESOURCES_FOLDER}' 中未找到。请重新输入。")
                        all_valid = False
                        break
                if all_valid:
                    if valid_files:
                        files_to_upload[param_name] = valid_files
                    break
        elif param_name in ["resemblance", "detail", "seed"]:
            while True:
                prompt_message = f"请输入可选参数 '{param_name}'"
                if param_name in ["resemblance", "detail"]:
                    prompt_message += " (1-100，可留空使用默认值): "
                elif param_name == "seed":
                     prompt_message += " (数字，可留空): "
                else:
                    prompt_message += " (可留空): "
                
                value_str = input(prompt_message).strip()
                
                if not value_str: # User skipped
                    user_params[param_name] = None 
                    break
                try:
                    value_int = int(value_str)
                    if param_name in ["resemblance", "detail"] and not (1 <= value_int <= 100):
                        print("相似度和细节值必须在1到100之间。")
                        continue
                    user_params[param_name] = value_int
                    break
                except ValueError:
                    print("请输入一个有效的数字。")
        elif param_name == "magic_prompt_option":
            while True:
                value_str = input(f"请输入可选参数 '{param_name}' (AUTO, ON, OFF，可留空使用默认 AUTO): ").strip().upper()
                if not value_str:
                    user_params[param_name] = "AUTO" # Default to AUTO if skipped
                    break
                if value_str in ["AUTO", "ON", "OFF"]:
                    user_params[param_name] = value_str
                    break
                else:
                    print("请输入 AUTO, ON, 或 OFF。")
        elif param_name == "upscale_prompt":
            value = input(f"请输入可选参数 '{param_name}' (辅助放大提示，可留空): ").strip()
            if value:
                 user_params[param_name] = value
            else:
                 user_params[param_name] = None # Explicitly None if empty
        else:
            value = input(f"请输入可选参数 '{param_name}' (可留空): ").strip()
            if value:
                user_params[param_name] = value
    
    return user_params, files_to_upload

def call_yunwu_api(api_key, func_name, func_details, user_data, files_data, is_describe_call=False):
    """调用云雾封装的 Ideogram API。"""
    full_url = YUNWU_BASE_URL.rstrip('/') + func_details["endpoint_suffix"]
    headers = {
        
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json"
        # Content-Type 会由 requests 根据 files 参数自动设置
    }

    # 修改：构建 files 参数为元组列表，以更好地处理重复字段名
    prepared_files_list = []
    opened_files_for_cleanup = [] # 用于确保之后关闭

    try:
        for param_key, file_info in files_data.items():
            if isinstance(file_info, list): # 多个文件路径字符串，如 style_reference_images
                for file_path in file_info:
                    file_obj = open(file_path, 'rb')
                    opened_files_for_cleanup.append(file_obj)
                    prepared_files_list.append((param_key, (os.path.basename(file_path), file_obj)))
            else: # 单个文件路径字符串
                file_path = file_info
                file_obj = open(file_path, 'rb')
                opened_files_for_cleanup.append(file_obj)
                prepared_files_list.append((param_key, (os.path.basename(file_path), file_obj)))
        

        # 打印将要上传的文件列表
        if prepared_files_list:
           # print(f"Files being uploaded (param_name, filename): {[(item[0], item[1][0]) for item in prepared_files_list]}")
            print(f"Files being uploaded {prepared_files_list}")
        else:
            print("No files being uploaded.")

        start_time = time.time() # 开始计时
        # print(f"正在调用 {func_name} API...") # 由外部步骤打印具体操作

        # --- BEGIN: Periodic time logging ---
        stop_event = threading.Event()
        
        # Helper function for logging time; defined inside call_yunwu_api to capture func_name
        # This function runs in a separate thread to print time while the API call is in progress.
        def log_time_elapsed_during_api_call(s_time, event, f_name):
            while not event.wait(1):  # Wait for 1 second or until event is set
                if event.is_set(): # Double check if event was set during wait, to exit promptly
                    break
                elapsed = time.time() - s_time
                print(f"计时: {elapsed:.2f} 秒")

        timer_thread = threading.Thread(target=log_time_elapsed_during_api_call, args=(start_time, stop_event, func_name))
        timer_thread.daemon = True # Set as daemon so it doesn't block program exit if main thread exits.
        timer_thread.start()
        # --- END: Periodic time logging ---
        
        try:
            response = requests.post(full_url, headers=headers, data=user_data, files=prepared_files_list, timeout=120)
        finally:
            # --- BEGIN: Stop periodic logging ---
            stop_event.set() # Signal the timer thread to stop
            if timer_thread.is_alive():
                 timer_thread.join(timeout=2) # Wait for the timer thread to finish, with a timeout
            # --- END: Stop periodic logging ---
        
        end_time = time.time() # 结束计时
        duration = end_time - start_time
        print(f"计时: {duration:.2f} 秒") # Modified "耗时" to "总耗时"

        # 关闭所有打开的文件句柄 (已移至finally块)

        response.raise_for_status() 
        
        response_json = None
        try:
            response_json = response.json()
          # print("API 原始响应 (JSON):")
          # print(json.dumps(response_json, indent=2, ensure_ascii=False)) # This line is now commented out
        except json.JSONDecodeError:
           #print(f"API 调用成功 (状态码 {response.status_code})，但响应不是有效的JSON格式。")
            #print("API 原始响应 (Text):")
            #print(response.text)
            if is_describe_call:
                return None 
            return [] 
        
        if is_describe_call and isinstance(response_json, dict) and "descriptions" in response_json:
           
            return response_json 

        elif not is_describe_call and isinstance(response_json, dict) and \
             "data" in response_json and isinstance(response_json["data"], list) and \
             "created" in response_json: 
           #print("成功解析 Ideogram API 直接响应 (例如 Replace Background)。")
            ideogram_data_list = response_json["data"]
            image_urls = []
            for item in ideogram_data_list:
                if "url" in item:
                    image_urls.append(item["url"])
            if not image_urls:
                print("错误: 在直接API响应的 'data' 数组中未找到图片URL。")
            return image_urls

        elif response_json.get("code") == 0 and "data" in response_json:
            yunwu_data = response_json["data"]
            
            if is_describe_call and isinstance(yunwu_data, dict) and "descriptions" in yunwu_data:
                print("成功解析 Describe API 响应 (云雾包装结构内)。")
                return yunwu_data 
            
            ideogram_data_list = [] 
            if isinstance(yunwu_data, list): 
                 ideogram_data_list = yunwu_data
            elif isinstance(yunwu_data, dict) and "created" in yunwu_data and "data" in yunwu_data and isinstance(yunwu_data["data"], list): 
                 ideogram_data_list = yunwu_data["data"]
            elif isinstance(yunwu_data, dict) and "data" in yunwu_data and isinstance(yunwu_data["data"], list): 
                ideogram_data_list = yunwu_data["data"]
            elif "task_id" in yunwu_data and "task_status" in yunwu_data: 
               #print(f"任务已提交，Task ID: {yunwu_data['task_id']}, Status: {yunwu_data['task_status']}")
                print("对于异步任务，您可能需要另一个函数来根据 Task ID 查询结果。")
                print("当前脚本主要处理同步返回图片URL的场景。")
                return [] 
            elif not is_describe_call: 
                 print("错误: API响应成功(包装)，但 'data' 内部结构无法解析以提取图片URL。")
                 print("云雾 data 字段")
                 return []
            elif is_describe_call: # is_describe_call is true, but previous describe checks failed
                print("Describe API 调用返回包装，但内部未找到")
                return None


            image_urls = []
            for item in ideogram_data_list:
                if "url" in item:
                    image_urls.append(item["url"])
            
            if not image_urls and not is_describe_call:
                print("错误: 在API响应中未找到图片URL。")
            return image_urls
        else:
            print(f"API 调用失败或返回非预期格式: {response_json.get('message', '未知错误')}")
            if is_describe_call:
                return None 
            return [] 

    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP 错误: {http_err}") # 打印http_err本身
        if hasattr(http_err, 'response') and http_err.response is not None: # Check if response exists
             print(f"响应内容: {http_err.response.text}") # 打印响应文本
    except requests.exceptions.RequestException as req_err:
        print(f"请求错误: {req_err}") # 打印req_err本身
    except Exception as e:
        print(f"处理API调用时发生未知错误: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        for f_obj in opened_files_for_cleanup:
            if hasattr(f_obj, 'closed') and not f_obj.closed:
                f_obj.close()
    return []


def download_image(image_url, original_filename_base, func_name_short):
    """下载图片并保存到成品文件夹。"""
    try:
        #print(f"正在下载图片: {image_url}")
        response = requests.get(image_url, stream=True, timeout=6000)
        response.raise_for_status()

        # 生成文件名
        # timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        timestamp_hms = datetime.now().strftime("%H%M%S") # 新的时间戳格式
        # 从URL获取可能的扩展名
        file_ext = os.path.splitext(image_url.split('?')[0])[-1]
        if not file_ext or len(file_ext) > 5 : # 基本的扩展名检查
            file_ext = ".png" # 默认png

        # 移除原始文件名的扩展名，以防万一
        original_base = os.path.splitext(original_filename_base)[0]

        # output_filename = f"{original_base}_{func_name_short}_{timestamp}{file_ext}"
        # 新的文件名格式
        output_filename = f"{original_base}_{timestamp_hms}{file_ext}"
        output_path = os.path.join(OUTPUT_FOLDER, output_filename)

        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"图片已保存到: {output_path}")
        return output_path
    except requests.exceptions.RequestException as e:
        print(f"下载图片失败: {e}")
    except Exception as e:
        print(f"保存图片时出错: {e}")
    return None

def process_selected_function(api_key, func_name, func_details):
    """处理用户选择的功能。"""
    user_form_data, files_to_upload_map = get_user_inputs_for_function(func_details)
    
    # 获取用于文件命名的原始图片名称 (如果存在)
    original_input_image_name = "generated" # 默认值

    # --- BEGIN: 处理固定参数 ---
    if "fixed_params" in func_details:
        for key, value in func_details["fixed_params"].items():
            user_form_data[key] = value
            # print(f"使用固定参数: {key} = {value}") # Optional: for debugging
    # --- END: 处理固定参数 ---

    # --- BEGIN: 特殊处理 Upscale 的 image_request ---
    if func_name == "放大高清 (Upscale)":
        image_request_dict = {}

        resemblance = user_form_data.pop("resemblance", None) 
        detail = user_form_data.pop("detail", None)       
        upscale_prompt = user_form_data.pop("upscale_prompt", None)
        magic_prompt_option = user_form_data.pop("magic_prompt_option", None) # Already defaults to AUTO in get_user_inputs
        seed = user_form_data.pop("seed", None)

        # 设置默认值或用户提供的值
        image_request_dict["resemblance"] = resemblance if resemblance is not None else 75 
        image_request_dict["detail"] = detail if detail is not None else 75
        
        # 只有当用户提供了这些值时才加入到 image_request_dict
        if upscale_prompt: # 如果用户提供了辅助prompt
            image_request_dict["prompt"] = urllib.parse.quote_plus(upscale_prompt)
        # else: 
            # 根据示例，prompt似乎总是存在于image_request中，即使只是一个通用的或空（URL编码后）
            # image_request_dict["prompt"] = "" # 或者一个默认的URL编码的提示，例如 "enhance%20detail"

        if magic_prompt_option: # magic_prompt_option 在 get_user_inputs 中已默认为 "AUTO"
            image_request_dict["magic_prompt_option"] = magic_prompt_option
        
        if seed is not None: # 如果用户提供了seed
            image_request_dict["seed"] = seed
        
        user_form_data["image_request"] = json.dumps(image_request_dict)
        # print(f"Constructed image_request for Upscale: {user_form_data['image_request']}") # For debugging
    # --- END: 特殊处理 Upscale 的 image_request --- 

    # --- BEGIN: 增强文生图的prompt以确保英文输出 ---
    if func_name == "文生图 (Generate V3)":
        if "prompt" in user_form_data and user_form_data["prompt"]:
            original_prompt = user_form_data["prompt"]
            # 确保追加的文本前有一个空格，如果原始prompt不以标点符号结尾
            separator = " " if original_prompt and not original_prompt.strip()[-1] in ['.', '!', '?'] else ""
            user_form_data["prompt"] = original_prompt + separator + "All text in the generated image must be in English and clearly legible."
            print(f"已自动为文生图Prompt追加英文指令。原始: '{original_prompt}', 修改后: '{user_form_data['prompt']}'")
        elif "prompt" not in user_form_data or not user_form_data["prompt"]:
             print("警告: 文生图的prompt为空，无法追加英文指令。")
    # --- END: 增强文生图的prompt ---

    # 'image' 是最常见的主输入图片参数名
    # Note: For Upscale, 'image_file' is now the key in files_to_upload_map
    if "image" in files_to_upload_map and isinstance(files_to_upload_map["image"], str):
        original_input_image_name = os.path.basename(files_to_upload_map["image"])
    elif files_to_upload_map: # 如果有其他文件参数，取第一个作为参考
        first_file_key = list(files_to_upload_map.keys())[0]
        first_file_val = files_to_upload_map[first_file_key]
        if isinstance(first_file_val, str):
             original_input_image_name = os.path.basename(first_file_val)
        elif isinstance(first_file_val, list) and first_file_val:
             original_input_image_name = os.path.basename(first_file_val[0])


    image_urls = call_yunwu_api(api_key, func_name, func_details, user_form_data, files_to_upload_map)

    if image_urls:
        print(f"成功获取 {len(image_urls)} 个图片URL。")
        func_name_short = func_name.split(" (")[0].replace(" ", "") # 简化功能名用于文件名
        for i, url in enumerate(image_urls):
            # 如果生成多张图，文件名稍作区分
            name_base = original_input_image_name
            if len(image_urls) > 1:
                name_base = f"{os.path.splitext(original_input_image_name)[0]}_img{i+1}"
            
            download_image(url, name_base, func_name_short)
    else:
        print("未能获取到图片URL或处理失败。")

# --- 新增：处理组合功能的函数 ---
def process_describe_and_fill_background(api_key):
    """实现 Describe JPG + Fill PNG Background 的逻辑。"""
    print(f"\n--- 开始执行: {DESCRIBE_AND_FILL_BACKGROUND_FUNC_NAME} ---")

    # 1. 自动查找 JPG 和 PNG 文件
    jpg_file_path = None
    png_file_path = None
    jpg_filename_for_saving = None # 用于后续保存时的文件名部分
    png_filename_for_saving = None # 用于后续保存时的文件名部分
    
    for filename in os.listdir(RESOURCES_FOLDER):
        if filename.lower().endswith(".jpg") and not jpg_file_path: # 只取第一个找到的
            jpg_file_path = os.path.join(RESOURCES_FOLDER, filename)
            jpg_filename_for_saving = filename # 保存原始文件名
            print(f"自动找到 JPG 文件: {filename}")
        elif filename.lower().endswith(".png") and not png_file_path: # 只取第一个找到的
            png_file_path = os.path.join(RESOURCES_FOLDER, filename)
            png_filename_for_saving = filename # 保存原始文件名
            print(f"自动找到 PNG 文件: {filename}")

    if not jpg_file_path:
        print(f"错误: 未能在 '{RESOURCES_FOLDER}' 文件夹中自动找到 JPG 文件。请确保文件存在。")
        return
    if not png_file_path:
        print(f"错误: 未能在 '{RESOURCES_FOLDER}' 文件夹中自动找到 PNG 文件。请确保文件存在。")
        return

    # 2. 调用 Describe API
    print("\n步骤1: 获取JPG图片的描述...")
    describe_func_details = IDEOGRAM_FUNCTIONS_YUNWU.get("图像描述 (Describe)")
    if not describe_func_details:
        print("错误: 在配置中找不到 '图像描述 (Describe)' 功能的定义。")
        return

    describe_files_data = {"image_file": jpg_file_path} # 使用新的参数名 image_file
    # Describe API 通常不需要额外的表单数据
    describe_response = call_yunwu_api(api_key, "图像描述 (Describe)", describe_func_details, {}, describe_files_data, is_describe_call=True)

    generated_prompt = ""
    # 修改: 移除"主体融合背景"相关内容
    ADDITIONAL_PROMPT_TEXT = " ,Highlight the product features and ensure product details are clearly visible. All text in the generated image must be in English and clearly legible."

    if describe_response and isinstance(describe_response, dict) and "descriptions" in describe_response:
        if describe_response["descriptions"]:
            base_prompt = describe_response["descriptions"][0].get("text", "")
            generated_prompt = base_prompt + ADDITIONAL_PROMPT_TEXT
            print(f"从JPG获取到的描述并追加指定文本后: {generated_prompt}")
            # 不再询问用户，直接使用
        else:
            print("Describe API 返回成功，但描述列表为空。")
    else:
        print("未能从 Describe API 获取有效描述。")
    
    if not generated_prompt: # 如果获取描述失败或描述为空
        print("无法自动生成描述。将尝试使用默认提示词 + 指定文本。")
        # 可以设置一个默认的基础提示词，或者让用户必须提供一个
        # 为简单起见，如果API失败，我们这里也只用追加的文本，但这可能效果不佳
        # 更好的做法可能是强制用户输入，或者有一个更通用的默认提示
        default_base_prompt = "A clear picture" # 示例默认基础提示词
        generated_prompt = default_base_prompt + ADDITIONAL_PROMPT_TEXT
        print(f"使用默认基础提示词并追加指定文本后: {generated_prompt}")
        # use_default = input("无法自动生成描述。是否手动输入提示词? (y/n): ").lower()
        # if use_default == 'y':
        #     generated_prompt = input("请输入提示词: ").strip()
        # else:
        #     print("没有提示词，无法继续。")
        #     return
        # if not generated_prompt:
        #      print("提示词为空，无法继续。")
        #      return

    print(f"最终使用的提示词: {generated_prompt}")

    # 3. 调用 Replace Background V3 API (或 Edit V3 作为备选)
    print("\n步骤2: 使用描述填充PNG图片的背景...")
    # 优先使用 Replace Background
    fill_func_choice_name = "替换背景 (Replace Background V3)"
    fill_func_details = IDEOGRAM_FUNCTIONS_YUNWU.get(fill_func_choice_name)
    
    if not fill_func_details:
        print(f"错误: 在配置中找不到 '{fill_func_choice_name}' 功能的定义。")
        return

    fill_user_data = {
        "prompt": generated_prompt,
        "num_images": 2  # 自动设置生成3张图片
    }
    # 可选：让用户输入 resolution for Replace Background
    rb_resolution = input(f"请输入替换背景后的分辨率 (例如 1024x1024，可留空使用默认): ").strip()
    if rb_resolution:
        fill_user_data["resolution"] = rb_resolution

    fill_files_data = {
        "image": png_file_path,
        # "style_reference_images": [os.path.join(RESOURCES_FOLDER, jpg_file_path)] # 可选：将JPG作为风格参考
    }
    
    # 询问是否将JPG用作风格参考 - 修改为自动使用
    # use_jpg_as_style = input("是否将JPG图片用作风格参考? (y/n，默认为n): ").strip().lower()
    # if use_jpg_as_style == 'y':
    if jpg_file_path: # 如果存在JPG文件，则自动用作风格参考
        print(f"自动将 {os.path.basename(jpg_file_path)} 用作风格参考。")
        style_ref_path = jpg_file_path 
        fill_files_data["style_reference_images"] = [style_ref_path] 
        # print(f"将使用 {os.path.basename(jpg_file_path)} 作为风格参考。")
    else:
        print("未找到JPG文件，不使用风格参考。")

    image_urls = call_yunwu_api(api_key, fill_func_choice_name, fill_func_details, fill_user_data, fill_files_data)

    if image_urls:
        print(f"成功获取 {len(image_urls)} 张背景填充后的图片URL。")
        # 使用PNG文件名作为基础，加上特定后缀
        # base_name_for_save = os.path.splitext(os.path.basename(png_file_path))[0]
        base_name_for_save = os.path.splitext(png_filename_for_saving)[0] if png_filename_for_saving else "filled_image"
        for i, url in enumerate(image_urls):
            name_base_final = base_name_for_save
            if len(image_urls) > 1:
                name_base_final = f"{base_name_for_save}_filled_bg_img{i+1}"
            else:
                name_base_final = f"{base_name_for_save}_filled_bg"
            download_image(url, name_base_final, "DescribeFill") # 使用一个独特的短功能名
    else:
        print("未能生成或获取填充背景后的图片URL。")

# --- 新增：处理 "智能图片重制" 的函数 ---
def process_describe_and_remix_image(api_key):
    """实现 Describe JPG + Remix PNG 的逻辑。"""
    print(f"\n--- 开始执行: {DESCRIBE_AND_REMIX_IMAGE_FUNC_NAME} ---")

    # 1. 自动查找 JPG 和 PNG 文件 (与 process_describe_and_fill_background 逻辑相同)
    jpg_file_path = None
    png_file_path = None
    jpg_filename_for_saving = None # 用于后续保存时的文件名部分 (虽然Remix不一定严格保留原名，但可用于日志)
    png_filename_for_saving = None # 用于后续保存时的文件名部分
    
    for filename in os.listdir(RESOURCES_FOLDER):
        if filename.lower().endswith(".jpg") and not jpg_file_path:
            jpg_file_path = os.path.join(RESOURCES_FOLDER, filename)
            jpg_filename_for_saving = filename
            print(f"自动找到 JPG 文件: {filename}")
        elif filename.lower().endswith(".png") and not png_file_path:
            png_file_path = os.path.join(RESOURCES_FOLDER, filename)
            png_filename_for_saving = filename
            print(f"自动找到 PNG 文件: {filename}")

    if not jpg_file_path:
        print(f"错误: 未能在 '{RESOURCES_FOLDER}' 文件夹中自动找到 JPG 文件。请确保文件存在。")
        print(f"当前文件夹内容:")
        # 对于Remix，JPG通常作为风格参考，如果仅有PNG也可以尝试，但我们的流程是基于JPG描述
        # 所以这里还是要求JPG必须存在
        return
    if not png_file_path:
        print(f"错误: 未能在 '{RESOURCES_FOLDER}' 文件夹中自动找到 PNG 文件。请确保文件存在。")
        return

    # 2. 调用 Describe API 获取JPG描述 (与 process_describe_and_fill_background 逻辑相同)
    print("\n步骤1: 获取JPG图片的描述...")
    describe_func_details = IDEOGRAM_FUNCTIONS_YUNWU.get("图像描述 (Describe)")
    if not describe_func_details:
        print("错误: 在配置中找不到 '图像描述 功能的定义。")
        return

    describe_files_data = {"image_file": jpg_file_path}
    describe_response = call_yunwu_api(api_key, "图像描述 ", describe_func_details, {}, describe_files_data, is_describe_call=True)

    generated_prompt = ""
    # 修改：移除"主体融合背景"相关内容
    ADDITIONAL_PROMPT_TEXT = " Highlight the product features and showcase product details clearly" 

    if describe_response and isinstance(describe_response, dict) and "descriptions" in describe_response:
        if describe_response["descriptions"]:
            base_prompt = describe_response["descriptions"][0].get("text", "")
            generated_prompt = base_prompt + ADDITIONAL_PROMPT_TEXT
            print(f"从JPG获取到的描述并追加指定文本后: {generated_prompt}")
        else:
            print("Describe API 返回成功，但描述列表为空。")
    else:
        print("未能从 Describe API 获取有效描述。")
    
    if not generated_prompt: # 如果获取描述失败或描述为空
        # 使用一个更适合产品重制的默认提示基础
        default_base_prompt = "A high-quality product image, well-lit and focused" 
        generated_prompt = default_base_prompt + ADDITIONAL_PROMPT_TEXT
        print(f"使用默认基础提示词并追加指定文本后: {generated_prompt}")

    print(f"最终使用的提示词 (用于Remix): {generated_prompt}")

    # 3. 调用 Remix V3 API
    print("\n步骤2: 使用描述和JPG(如果存在)风格重制PNG图像...")
    remix_func_choice_name = "图片重制 (Remix V3)"
    remix_func_details = IDEOGRAM_FUNCTIONS_YUNWU.get(remix_func_choice_name)
    
    if not remix_func_details:
        print(f"错误: 在配置中找不到功能的定义。")
        return

    remix_user_data = {
        "prompt": generated_prompt,
        "num_images": 3  # 自动设置生成3张图片, 与背景替换的逻辑一致
    }
    # 可选：让用户输入 resolution (Remix V3 支持此参数)
    remix_resolution = input(f"请输入图片重制后的分辨率 (例如 1024x1024，可留空使用默认): ").strip()
    if remix_resolution:
        remix_user_data["resolution"] = remix_resolution
    
    # Remix V3 特有的可选参数: image_weight (0.0 to 1.0, default 0.5)
    # 暂时不主动设置，使用API默认值。如果需要，后续可以添加用户输入。
    # print("提示: image_weight 参数将使用API默认值 (通常是0.5)。")

    remix_files_data = {
        "image": png_file_path, # 主图是PNG
    }
    
    # 自动将JPG用作风格参考 (如果存在)
    if jpg_file_path:
        print(f"自动将 {os.path.basename(jpg_file_path)} 用作风格参考。")
        # Remix API 期望 style_reference_images 是一个文件列表
        remix_files_data["style_reference_images"] = [jpg_file_path] 
    else:
        print("未找到JPG文件，不使用风格参考 (Remix可能仍能主要基于主图和提示词工作)。")

    image_urls = call_yunwu_api(api_key, remix_func_choice_name, remix_func_details, remix_user_data, remix_files_data)

    if image_urls:
        print(f"成功获取 {len(image_urls)} 张重制后的图片URL。")
        # 使用PNG文件名作为基础，加上特定后缀
        base_name_for_save = os.path.splitext(png_filename_for_saving)[0] if png_filename_for_saving else "remixed_image"
        func_name_short = "DescribeRemix" 
        for i, url in enumerate(image_urls):
            name_base_final = base_name_for_save
            if len(image_urls) > 1:
                name_base_final = f"{base_name_for_save}_remix_img{i+1}"
            else:
                name_base_final = f"{base_name_for_save}_remix"
            download_image(url, name_base_final, func_name_short) 
    else:
        print("未能生成或获取重制后的图片URL。")

# --- 新增：处理从亚马逊获取信息并生成提示词的函数 (使用标准Playwright) ---
def get_amazon_product_info_and_generate_prompt_for_edit(api_key):
    """当本地没有JPG风格参考时，尝试从亚马逊商品页面获取信息生成提示词。
    使用标准Playwright库而不是MCP服务。
    现在会为下载的每张图片生成单独的提示词，并返回一个列表。
    增强了品牌名称移除逻辑。"""
    amazon_url = input("请输入亚马逊商品页面的URL (例如 https://www.amazon.com/dp/B074P5K4QV)，或直接回车跳过: ").strip()
    if not amazon_url:
        print("用户未提供亚马逊URL，跳过此步骤。")
        return None

    print(f"准备从以下URL获取商品信息: {amazon_url}")

    if not PLAYWRIGHT_AVAILABLE:
        print("错误: Playwright库未安装，无法获取亚马逊商品信息。")
        print("您可以使用pip安装: pip install playwright")
        print("然后安装浏览器驱动: playwright install")
        return None

    # 移除询问是否显示浏览器窗口，默认设置为显示
    show_browser = True
    print("将使用可见浏览器模式，以避免验证码问题。请在需要时手动处理验证码。")

    # 移除询问步骤，直接设置为下载
    should_download_images = True
    print("将自动下载商品主图到'素材'文件夹并为每张生成提示词。")

    product_title = None
    product_features = []
    main_image_alts_for_fallback = []
    product_description = ""
    downloaded_image_paths_summary = []
    brand_name = None # 初始化 brand_name

    image_sources = [] # Stores {"url": "...", "alt": "..."}

    try:
        print("\n步骤 1: 启动Playwright浏览器并导航到亚马逊商品页面...")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not show_browser)
            page = browser.new_page()
            page.set_extra_http_headers({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9"
            })
            print(f"导航到URL: {amazon_url}")
            response = page.goto(amazon_url, wait_until="domcontentloaded", timeout=60000)

            if response.status >= 400:
                print(f"错误: 无法访问URL，HTTP状态码: {response.status}")
                browser.close()
                return None

            # 检查是否出现验证码页面，如果出现，尝试自动点击"Try different image"按钮
            captcha_selectors = [
                "input[name='captchacharacters']",  # 验证码输入框
                "form[action='/errors/validateCaptcha']",  # 验证码表单
                "img[src*='captcha']",  # 验证码图片
                "a:has-text('Try different image')"  # "Try different image"链接
            ]
            
            try:
                # 检测验证码页面
                for selector in captcha_selectors:
                    captcha_element = page.query_selector(selector)
                    if captcha_element:
                        print("检测到验证码页面，尝试自动跳过...")
                        # 尝试点击"Try different image"按钮
                        try_different_btn = page.query_selector("a:has-text('Try different image')")
                        if try_different_btn:
                            print("找到'Try different image'按钮，尝试点击...")
                            try_different_btn.click()
                            print("已点击'Try different image'按钮，等待页面加载...")
                            
                            # 等待页面加载完成
                            try:
                                # 等待页面主体元素加载
                                page.wait_for_selector('body', state='attached', timeout=5000)
                                #print("页面已加载，开始滚动...")
                                
                                # 简单的滚动：向下滚动500像素
                                page.evaluate("window.scrollBy(0, 500)")
                                # 等待2秒
                                page.wait_for_timeout(2000)
                                # 再向下滚动500像素
                                page.evaluate("window.scrollBy(0, 500)")
                                #print("页面滚动完成")
                                
                            except Exception as e:
                                print(f"滚动页面时出错: {e}")
                            
                            page.wait_for_timeout(5000)  # 等待5秒
                            
                            print("已点击'Try different image'按钮，等待5秒...")
                            
                            # 添加从上往下的滚动效果，模拟真实浏览行为
                            try:
                                # 获取页面总高度
                                page_height = page.evaluate("document.body.scrollHeight")
                                # 设置初始滚动位置为0
                                current_position = 0
                                # 设置滚动步长（每次滚动的像素数）
                                scroll_step = 300
                                # 设置滚动间隔时间（毫秒）
                                scroll_interval = 500
                                
                                # 从上往下滚动，直到到达页面底部
                                while current_position < page_height:
                                    # 计算下一次滚动的位置
                                    next_position = min(current_position + scroll_step, page_height)
                                    # 平滑滚动到下一个位置
                                    page.evaluate(f"window.scrollTo({{top: {next_position}, behavior: 'smooth'}})")
                                    # 更新当前位置
                                    current_position = next_position
                                    # 等待一小段时间，让滚动看起来更自然
                                    page.wait_for_timeout(scroll_interval)
                                
                                # 滚动到底部后，再等待一小段时间
                                page.wait_for_timeout(1000)
                                
                                # 最后滚动回顶部
                                page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
                                page.wait_for_timeout(1000)
                                
                            except Exception as scroll_error:
                                print(f"滚动页面时出错: {scroll_error}")
                            
                            page.wait_for_timeout(5000)  # 等待8秒
                            
                            # 再次检查是否仍需验证
                            still_captcha = False
                            for sel in captcha_selectors:
                                if page.query_selector(sel):
                                    still_captcha = True
                                    break
                            
                            if still_captcha:
                                print("仍然需要验证，请手动处理...")
                            else:
                                print("可能已成功跳过验证！")
                                break
                        else:
                            print("未找到'Try different image'按钮")
                        break
            except Exception as e:
                print(f"尝试自动跳过验证码时出错: {e}")
                
            # 检查是否仍需验证码
            needs_manual_verification = False
            for selector in captcha_selectors:
                if page.query_selector(selector):
                    needs_manual_verification = True
                    break
                    
            if needs_manual_verification:
                # 如果自动跳过失败，提示用户手动处理
                print("\n自动跳过验证码失败。请手动完成以下操作：")
                print("1. 尝试点击'Try different image'按钮切换图片，可能会跳过验证")
                print("2. 如果仍需验证，请手动完成验证或登录")
                input("完成验证后按回车键继续...")
            else:
                print("未检测到验证码页面或已成功自动跳过，继续执行...")

            print("等待页面加载 (最长30秒)...")
            try:
                page.wait_for_selector("#productTitle, #landingImage, #feature-bullets", timeout=30000)
            except Exception:
                print("页面关键元素加载超时或未找到，将尝试继续提取。")
                try:
                    # 再次尝试等待可能的产品元素
                    page.wait_for_selector("div.a-section, div#centerCol, div.a-box", timeout=10000)
                except Exception:
                    pass

            print("\n开始提取商品信息...")
            try:
                title_element = page.query_selector("#productTitle")
                if title_element:
                    product_title = title_element.inner_text().strip()
                    print(f"提取到商品标题: {product_title}")
                else:
                    print("未找到商品标题元素 (#productTitle)")
            except Exception as e:
                print(f"提取商品标题时出错: {e}")

            try:
                bullet_elements = page.query_selector_all("#feature-bullets li:not(.aok-hidden) span.a-list-item")
                if bullet_elements:
                    for bullet in bullet_elements:
                        text = bullet.inner_text().strip()
                        if text and len(text) > 5:
                            product_features.append(text)
                    print(f"提取到 {len(product_features)} 个卖点/产品特性")
                else:
                    print("未找到商品卖点元素，尝试备用选择器...")
                    # 尝试多个备用选择器来获取产品特点列表
                    feature_selectors = [
                        "div[id='feature-bullets'] li:not(.aok-hidden)",
                        "div.a-section.a-spacing-medium.a-spacing-top-small li", 
                        "div#featurebullets_feature_div ul.a-unordered-list li",
                        "div#productDescription ul li",
                        "div#dpx-product-description_feature_div ul li",
                        "div#technicalSpecifications_feature_div ul li",
                        "div.product-facts-detail ul li",
                        "div.a-expander-content ul li"
                    ]
                    
                    for selector in feature_selectors:
                        backup_bullets = page.query_selector_all(selector)
                        if backup_bullets:
                            features_found = 0
                            for bullet in backup_bullets:
                                text = bullet.inner_text().strip()
                                if text and len(text) > 5 and ":" not in text[0:4]:  # 避免获取表格式的项目
                                    product_features.append(text)
                                    features_found += 1
                            if features_found > 0:
                                print(f"通过备用选择器 '{selector}' 提取到 {features_found} 个卖点/产品特性")
                                break
            except Exception as e:
                print(f"提取商品卖点时出错: {e}")

            try:
                byline_info_element = page.query_selector("#bylineInfo")
                if byline_info_element:
                    byline_text = byline_info_element.inner_text().strip()
                    visit_store_match = re.search(r"Visit the\s+(.+?)\s+Store", byline_text, re.IGNORECASE)
                    if visit_store_match:
                        brand_name = visit_store_match.group(1).strip()
                        print(f"提取到品牌名称 (来自 'Visit Store' 链接): {brand_name}")
                    else:
                        brand_match = re.search(r"Brand:\s*(.+)", byline_text, re.IGNORECASE)
                        if brand_match:
                            brand_link_element = byline_info_element.query_selector("a")
                            if brand_link_element:
                                brand_name = brand_link_element.inner_text().strip()
                            else:
                                brand_name = brand_match.group(1).strip()
                            print(f"提取到品牌名称 (来自 'Brand:' 文本): {brand_name}")

                if not brand_name:
                    brand_selectors_fallback = [
                        "div#centerCol div#bylineInfo_feature_div a.a-link-normal[href*='/stores/']",
                        "div#centerCol div#bylineInfo_feature_div a.a-link-normal[href*='/BRAND/']",
                        "div#productOverview_feature_div tr:has(td.a-span3:has-text('Brand')) td.a-span9 span.a-size-base",
                        "div#detailBullets_feature_div li:has(span.a-text-bold:contains('Brand')) > span > span:nth-of-type(2)"
                    ]
                    for selector in brand_selectors_fallback:
                        brand_element_fb = page.query_selector(selector)
                        if brand_element_fb:
                            extracted_text = brand_element_fb.inner_text().strip()
                            if "Visit the" in extracted_text and "Store" in extracted_text:
                                 store_match = re.search(r"Visit the\s+(.+?)\s+Store", extracted_text, re.IGNORECASE)
                                 if store_match:
                                     brand_name = store_match.group(1).strip()
                            elif extracted_text:
                                brand_name = extracted_text
                            if brand_name:
                                print(f"提取到品牌名称 (来自备用选择器 '{selector}'): {brand_name}")
                                break
            except Exception as e:
                print(f"提取品牌名称时出错: {e}")

            try:
                main_image_selectors = ["#landingImage", "#imgTagWrapperId img", "#imgBlkFront", "#ivLargeImage img"]
                for selector in main_image_selectors:
                    main_img_element = page.query_selector(selector)
                    if main_img_element:
                        main_img_url_attr = main_img_element.get_attribute("src")
                        if not main_img_url_attr:
                           main_img_url_attr = main_img_element.get_attribute("data-src")
                        main_img_alt = main_img_element.get_attribute("alt") or ""
                        if main_img_url_attr:
                            main_img_url = urllib.parse.urljoin(amazon_url, main_img_url_attr)
                            hires_main_url = re.sub(r'\._.*?_\.', '._SL1600_.', main_img_url) if isinstance(main_img_url, str) else main_img_url
                            if not any(src["url"] == hires_main_url for src in image_sources):
                                image_sources.append({"url": hires_main_url, "alt": main_img_alt})
                                if main_img_alt and main_img_alt not in main_image_alts_for_fallback:
                                    main_image_alts_for_fallback.append(main_img_alt)
                                print(f"提取到主图URL (尝试高分): {hires_main_url}, Alt: {main_img_alt[:50]}...")
                            break

                thumb_img_elements = page.query_selector_all(
                    "#altImages ul li img, #altImages .a-list-item img, #imageBlock_feature_div img, #thumbsBelowVisualSearchCarousel img, #thumbImages img, #image-block-pagination img"
                )
                print(f"找到 {len(thumb_img_elements)} 个潜在的缩略图元素。")
                for img_element in thumb_img_elements:
                    img_url_attr = img_element.get_attribute("src")
                    if not img_url_attr:
                        img_url_attr = img_element.get_attribute("data-src")
                    img_alt = img_element.get_attribute("alt") or ""
                    if img_url_attr and "sprite" not in img_url_attr.lower() and "loading" not in img_url_attr.lower() and "grey-pixel" not in img_url_attr.lower():
                        img_url = urllib.parse.urljoin(amazon_url, img_url_attr)
                        hires_url = img_url
                        if isinstance(img_url, str):
                            hires_url = re.sub(r'\._SS[0-9]+(?:_[A-Z0-9]+)?_\.', '._SL1600_.', hires_url)
                            hires_url = re.sub(r'\._AC_US[0-9]+_\.', '._SL1600_.', hires_url)
                            hires_url = re.sub(r'\._UX[0-9]+_\.', '._SL1600_.', hires_url)
                            hires_url = re.sub(r'\._SY[0-9]+_\.', '._SL1600_.', hires_url)
                            if hires_url == img_url:
                                hires_url = re.sub(r'\._.*?_\.(jpg|png|jpeg)', r'._SL1600_.\1', hires_url, flags=re.IGNORECASE)
                            if hires_url == img_url:
                                if '._' in hires_url:
                                     base_part = hires_url.split('._')[0]
                                     ext_match = re.search(r'\.(jpg|jpeg|png|gif)$', hires_url, re.IGNORECASE)
                                     if ext_match:
                                         hires_url = base_part + ext_match.group(0)
                                     else:
                                         hires_url = base_part
                        hires_url = urllib.parse.urljoin(amazon_url, hires_url)
                        if not any(src["url"] == hires_url for src in image_sources):
                            image_sources.append({"url": hires_url, "alt": img_alt})
                            if img_alt and img_alt not in main_image_alts_for_fallback:
                                main_image_alts_for_fallback.append(img_alt)
                            print(f"提取到附加图URL (尝试高分): {hires_url}, Alt: {img_alt[:50]}...")

                seen_urls = set()
                unique_image_sources = []
                for src in image_sources:
                    if src["url"] not in seen_urls:
                        unique_image_sources.append(src)
                        seen_urls.add(src["url"])
                image_sources = unique_image_sources
                print(f"总共收集到 {len(image_sources)} 个独特的图片源。")
            except Exception as e:
                print(f"提取图片信息时出错: {e}")

            try:
                desc_element = page.query_selector("#productDescription")
                if desc_element:
                    product_description = desc_element.inner_text().strip()
                    print(f"提取到商品描述 (长度: {len(product_description)} 字符)")
                
                # 即使找到了描述，也尝试查找更多详细信息
                description_selectors = [
                    "#productDescription",
                    "#aplus", 
                    ".aplus-v2", 
                    "#aplus3p_feature_div", 
                    "#askAplus_feature_div",
                    "#dpx-product-description_feature_div",
                    "#productDetails_feature_div",
                    "#productDetails_techSpec_section_1",
                    "#detailBulletsWrapper_feature_div",
                    "#detailBullets_feature_div",
                    "#prodDetails",
                    "div.product-facts-detail"
                ]
                
                for selector in description_selectors:
                    desc_elem = page.query_selector(selector)
                    if desc_elem:
                        desc_text = desc_elem.inner_text().strip()
                        if desc_text and len(desc_text) > 100:  # 确保获得有意义的描述
                            if not product_description:
                                product_description = desc_text
                                print(f"提取到商品描述 (从选择器 '{selector}', 长度: {len(product_description)} 字符)")
                            elif len(desc_text) > len(product_description) * 1.2:  # 如果新描述比当前描述长20%以上
                                print(f"发现更详细的商品描述 (从选择器 '{selector}', 长度: {len(desc_text)} 字符)")
                                product_description = desc_text
                
                # 特别处理详细规格表格，这些通常包含宝贵的产品特点但不在常规描述中
                spec_selectors = [
                    "table.a-keyvalue tr",
                    "#productDetails_techSpec_section_1 tr", 
                    "#productDetails_techSpec_section_2 tr",
                    "#technicalSpecifications_section_1 tr"
                ]
                
                specs_found = 0
                for selector in spec_selectors:
                    spec_rows = page.query_selector_all(selector)
                    for row in spec_rows:
                        try:
                            key_elem = row.query_selector("th") or row.query_selector("td.a-span3")
                            value_elem = row.query_selector("td:not(.a-span3)") or row.query_selector("td.a-span9")
                            
                            if key_elem and value_elem:
                                key = key_elem.inner_text().strip()
                                value = value_elem.inner_text().strip()
                                if key and value and key != "Customer Reviews":  # 排除评分相关
                                    spec_text = f"{key}: {value}"
                                    product_features.append(spec_text)
                                    specs_found += 1
                        except Exception as row_err:
                            continue  # 跳过处理有问题的行
                
                if specs_found > 0:
                    print(f"从规格表中提取到 {specs_found} 个产品特点")
                    
                # 确保没有重复的特点
                product_features = list(set(product_features))
                
                if not product_description and product_features:
                    # 如果没有找到描述但有特点，将特点组合成描述
                    product_description = "Product features: " + " ".join(product_features)
                    print(f"没有找到常规描述，已根据产品特点创建描述 (长度: {len(product_description)} 字符)")
            except Exception as e:
                print(f"提取商品描述时出错: {e}")

            browser.close()
            print("浏览器会话已关闭")

        all_results = []
        MAX_IMAGES_TO_PROCESS = 5

        # --- Helper function for robust brand removal ---
        def remove_brand_from_text(text_content, brand_to_remove):
            if not text_content or not brand_to_remove:
                return text_content
            
            # 1. Try removing if text starts with brand (case-insensitive)
            if text_content.lower().startswith(brand_to_remove.lower()):
                processed_text = text_content[len(brand_to_remove):].strip()
                # Clean common leading non-alphanumeric characters after brand removal, but keep ( or [
                processed_text = re.sub(r"^\s*[^a-zA-Z0-9(\[]+", "", processed_text).strip()
                if processed_text: # Only return if something is left
                    # print(f"    (Debug) Brand '{brand_to_remove}' removed from start. Original: '{text_content}', New: '{processed_text}'")
                    return processed_text
                # If removing from start results in empty, original text might be better or just brand
                # Fall through to general regex removal in this case or if not starting with brand

            # 2. General regex removal (whole word, case-insensitive)
            # This handles cases where brand is not at the start or if start-removal was too aggressive
            try:
                # Escape brand_to_remove for regex, especially if it contains special characters
                escaped_brand = re.escape(brand_to_remove)
                # \b ensures whole word matching. 
                # Using a regex allows for more complex patterns if needed in future.
                # We'll replace with an empty string.
                # The (?i) flag makes the pattern case-insensitive for the whole regex.
                # Or use flags=re.IGNORECASE in re.sub
                # pattern = r'\b' + escaped_brand + r'\b'
                # processed_text = re.sub(pattern, '', text_content, flags=re.IGNORECASE).strip()
                
                # Simpler approach that often works: direct case-insensitive replace
                # This can be problematic if brand is a substring of other words, but less so for product titles/features.
                # Let's stick to regex for safety with \b word boundaries.
                
                # Find all occurrences of the brand (case-insensitive)
                matches = list(re.finditer(r'\b' + escaped_brand + r'\b', text_content, re.IGNORECASE))
                if matches:
                    # Build the new string by taking parts not matching the brand
                    new_text_parts = []
                    current_pos = 0
                    for match in matches:
                        new_text_parts.append(text_content[current_pos:match.start()])
                        current_pos = match.end()
                    new_text_parts.append(text_content[current_pos:])
                    processed_text = "".join(new_text_parts).strip()

                    # Clean up multiple spaces that might result from removal
                    processed_text = re.sub(r'\s{2,}', ' ', processed_text).strip()
                    # Clean common leading/trailing non-alphanumeric junk, but keep ( or [
                    processed_text = re.sub(r"^\s*[^a-zA-Z0-9(\[]+", "", processed_text).strip()
                    processed_text = re.sub(r"[^a-zA-Z0-9)\]]\s*$", "", processed_text).strip() # Keep ) or ] at end
                    
                    if processed_text and processed_text.lower() != brand_to_remove.lower():
                        # print(f"    (Debug) Brand '{brand_to_remove}' removed via regex. Original: '{text_content}', New: '{processed_text}'")
                        return processed_text
            except Exception as e_regex:
                # print(f"    (Debug) Regex error during brand removal: {e_regex}")
                pass # Fallback to original text if regex fails
            
            # print(f"    (Debug) Brand '{brand_to_remove}' not removed from '{text_content}' by any method.")
            return text_content # Return original if no robust removal was done

        if should_download_images and image_sources:
            print(f"\n步骤 2: 下载商品图片(尝试从第3张开始，最多{MAX_IMAGES_TO_PROCESS}张)并为每张生成提示词...")
            os.makedirs(RESOURCES_FOLDER, exist_ok=True)

            short_product_name = "amazon_product"
            if product_title:
                temp_short_title = remove_brand_from_text(product_title, brand_name) if brand_name else product_title
                words = temp_short_title.split()
                short_product_name = "_".join(words[:3]).lower()
                short_product_name = "".join(c if c.isalnum() or c == '_' else '' for c in short_product_name)
                if not short_product_name: short_product_name = "amazon_product"


            successful_downloads_count = 0
            processed_urls_for_prompt = set()
            start_index = 2
            
            if len(image_sources) > start_index:
                target_image_sources = image_sources[start_index : start_index + MAX_IMAGES_TO_PROCESS]
                print(f"  将从图片源列表的第 {start_index + 1} 张开始，目标处理 {len(target_image_sources)} 张图片。")
            else:
                target_image_sources = []
                print(f"  图片源列表不足 {start_index + 1} 张，无法按要求跳过前两张图片。")

            for i, img_info in enumerate(target_image_sources):
                if successful_downloads_count >= MAX_IMAGES_TO_PROCESS:
                    break
                current_img_url = img_info["url"]
                current_img_alt = img_info["alt"]
                if current_img_url in processed_urls_for_prompt:
                    continue

                try:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    url_path = urllib.parse.urlparse(current_img_url).path
                    ext = os.path.splitext(url_path)[1]
                    if not ext or len(ext) > 5 or len(ext) < 3: ext = ".jpg"
                    img_filename = f"{short_product_name}_{i+1}_{timestamp}{ext}"
                    img_path = os.path.join(RESOURCES_FOLDER, img_filename)

                    print(f"  正在下载图片 {successful_downloads_count + 1}/{MAX_IMAGES_TO_PROCESS} (源列表索引 {i}): {current_img_url}")
                    img_response = requests.get(current_img_url, timeout=20)
                    if img_response.status_code == 200:
                        content_type = img_response.headers.get('content-type')
                        if content_type:
                            new_ext = ext
                            if 'jpeg' in content_type: new_ext = '.jpg'
                            elif 'png' in content_type: new_ext = '.png'
                            elif 'gif' in content_type: new_ext = '.gif'
                            if new_ext != ext:
                                ext = new_ext
                                img_filename = f"{short_product_name}_{i+1}_{timestamp}{ext}"
                                img_path = os.path.join(RESOURCES_FOLDER, img_filename)
                        with open(img_path, 'wb') as img_file:
                            img_file.write(img_response.content)
                        print(f"  图片已保存到: {img_path}")
                        downloaded_image_paths_summary.append(img_path)
                        successful_downloads_count += 1
                        processed_urls_for_prompt.add(current_img_url)

                        prompt_elements = []
                        title_for_prompt = remove_brand_from_text(product_title, brand_name) if product_title else "Product image"
                        if title_for_prompt:
                            prompt_elements.append(f"Product: {title_for_prompt}.")
                        
                        # 修改为每张图片突出显示一个不同的产品特点
                        if product_features:
                            # 确保不超出特点列表范围
                            feature_index = successful_downloads_count - 1  # 从0开始索引
                            if feature_index < len(product_features):
                                # 获取当前图片对应的单个特点
                                current_feature = product_features[feature_index]
                                # 移除品牌名称
                                cleaned_feature = remove_brand_from_text(current_feature, brand_name)
                                if cleaned_feature and cleaned_feature.lower() != brand_name.lower():
                                    # 添加为唯一的特点，突出显示
                                    prompt_elements.append(f"KEY FEATURE TO HIGHLIGHT IN THIS IMAGE: {cleaned_feature.strip().rstrip('.')}.")
                                    print(f"  为图片 {successful_downloads_count} 选择的特点: {cleaned_feature}")
                            else:
                                # 如果特点数量不足，使用通用文本或提示
                                prompt_elements.append(f"General product showcase image highlighting overall features.")
                                print(f"  特点数量不足，为图片 {successful_downloads_count} 使用通用提示")
                        
                        if current_img_alt:
                            cleaned_alt_for_prompt = remove_brand_from_text(current_img_alt, brand_name)
                            cleaned_alt_for_prompt = re.sub(r'\s+', ' ', cleaned_alt_for_prompt).strip()
                            alt_keywords = [w for w in cleaned_alt_for_prompt.split() if len(w) > 2 and w.lower() not in
                                            ["the", "and", "for", "with", "amazon", "product", "image", "picture", "view", "item", "style", "color", "shows", "model", "alternate", "gallery", "thumbnail"]
                                            + ([brand_name.lower()] if brand_name else []) ] # also exclude brand name from keywords
                            if alt_keywords:
                                prompt_elements.append(f"This specific image focuses on: {', '.join(alt_keywords[:6])}.")
                            elif len(cleaned_alt_for_prompt) > 10 and len(cleaned_alt_for_prompt) < 150 and cleaned_alt_for_prompt.lower() != brand_name.lower():
                                prompt_elements.append(f"Image details: {cleaned_alt_for_prompt}.")
                        
                        prompt_elements.append("Visual style: Ultra-realistic product photography, sharp focus, intricate details, professional studio lighting, clean background unless contextually relevant.")
                        prompt_elements.append("Composition: Dynamic angle if appropriate, or standard e-commerce shot. Highlight key product attributes visible in this specific image.")
                        prompt_elements.append("Impression: Commercial-grade, highly attractive, enticing for online shoppers.")
                        prompt_elements.append("Ensure all text in the generated image is in English, legible, and contextually correct if any text is part of the product design.")
                        
                        specific_prompt = " ".join(prompt_elements)
                        print(f"  为图片 {os.path.basename(img_path)} 生成的特定提示词 (部分): {specific_prompt[:120]}...")
                        all_results.append({"prompt": specific_prompt, "reference_image": img_path})
                    else:
                        print(f"  下载图片失败，HTTP状态码: {img_response.status_code} for URL: {current_img_url}")
                except Exception as e:
                    print(f"  下载或处理图片 {current_img_url} 时出错: {e}")
            
            if successful_downloads_count == 0 and image_sources:
                print("未能成功下载任何选定的商品图片。将尝试生成通用提示词。")

        if not all_results:
            if not product_title and not product_features and not main_image_alts_for_fallback:
                print("\n未能从页面提取到足够信息以生成有效提示词。")
                return None
            
            print("\n生成通用提示词 (因未选择下载图片、未找到图片源或所有下载均失败)...")
            prompt_elements = []
            title_for_prompt_generic = remove_brand_from_text(product_title, brand_name) if product_title else "Product image"
            if title_for_prompt_generic:
                prompt_elements.append(f"Product: {title_for_prompt_generic}.")

            if product_features:
                cleaned_features_generic = [remove_brand_from_text(f, brand_name) for f in product_features[:3]]
                cleaned_features_generic = [f for f in cleaned_features_generic if f and f.lower() != brand_name.lower()]
                if cleaned_features_generic:
                    features_text_generic = ", ".join([f.strip().rstrip('.') for f in cleaned_features_generic])
                    prompt_elements.append(f"Key features: {features_text_generic}.")
            
            generic_image_keywords = []
            if main_image_alts_for_fallback:
                for alt_idx, alt in enumerate(main_image_alts_for_fallback[:2]):
                    cleaned_alt_generic = remove_brand_from_text(alt, brand_name)
                    words = cleaned_alt_generic.split()
                    filtered_words = [w for w in words if len(w) > 3 and w.lower() not in
                                     ["the", "and", "for", "with", "amazon", "product", "image", "picture", "view"]
                                     + ([brand_name.lower()] if brand_name else [])]
                    generic_image_keywords.extend(filtered_words[:5])
                if generic_image_keywords:
                    prompt_elements.append(f"General visual elements from page: {', '.join(list(set(generic_image_keywords)))}.")
            
            if not generic_image_keywords: # If no specific visual elements derived from alt text
                 prompt_elements.append("Visual style: High-quality product photography with clear details and professional lighting.")

            prompt_elements.append("Scene context: Clean background or contextually relevant environment that highlights the product's purpose.")
            prompt_elements.append("Impression: Professional, attractive, commercial-grade product image that appeals to potential buyers.")
            prompt_elements.append("All text in the generated image must be in English and clearly legible.")
            
            generic_prompt = " ".join(prompt_elements)
            print(f"  通用提示词 (部分): {generic_prompt[:120]}...")
            all_results.append({"prompt": generic_prompt, "reference_image": None})

        print("\n--- 提取到的亚马逊商品信息摘要 ---")
        print(f"商品URL: {amazon_url}")
        print(f"标题: {product_title or '未提取到'}")
        if brand_name: print(f"提取到的品牌: {brand_name}")
        if product_features:
            print("\n核心卖点 (LIST):")
            for i, bullet in enumerate(product_features[:5]): print(f"  {i+1}. {bullet}")
        else: print("\n核心卖点: 未提取到")
        
        if downloaded_image_paths_summary:
            print("\n成功下载的图片:")
            for i, path in enumerate(downloaded_image_paths_summary): print(f"  图{i+1}: {os.path.basename(path)}")
        elif should_download_images and image_sources :
             print("\n下载的图片: 无 (尝试下载但全部失败)")
        elif should_download_images and not image_sources:
             print("\n下载的图片: 无 (未找到图片源)")
        
        print("-------------------------------------------")
        
        # 将生成的提示词保存到1.txt文件
        if all_results:
            try:
                with open("1.txt", "w", encoding="utf-8") as f:
                    for i, result in enumerate(all_results):
                        f.write(f"===== 提示词 {i+1} =====\n")
                        f.write(result["prompt"] + "\n\n")
                print(f"已将所有提示词保存到 1.txt 文件")
            except Exception as e:
                print(f"保存提示词到文件时出错: {e}")
                
        return all_results if all_results else None

    except Exception as e:
        print(f"处理亚马逊信息时发生严重错误: {e}")
        import traceback
        traceback.print_exc()
        return None

def process_describe_and_edit_image(api_key, product_info=None):
    """
    处理图片编辑功能。
    如果提供了product_info参数，则使用它来处理商品图片。
    否则，让用户手动选择图片。
    """
    # 检查素材文件夹是否存在
    if not os.path.exists(RESOURCES_FOLDER):
        print(f"错误: 未找到素材文件夹 '{RESOURCES_FOLDER}'")
        return

    # 如果没有提供商品信息，让用户手动选择图片
    if not product_info:
        # 获取素材文件夹中的所有JPG文件
        jpg_files = [f for f in os.listdir(RESOURCES_FOLDER) if f.lower().endswith('.jpg')]
        if not jpg_files:
            print("错误: 素材文件夹中没有JPG文件。")
            return

        print("\n可用的JPG文件:")
        for i, jpg_file in enumerate(jpg_files):
            print(f"{i+1}. {jpg_file}")

        while True:
            try:
                choice = int(input("\n请选择要处理的JPG文件序号: ")) - 1
                if 0 <= choice < len(jpg_files):
                    selected_jpg = jpg_files[choice]
                    break
                else:
                    print("无效的选择，请重试。")
            except ValueError:
                print("请输入数字序号。")

        jpg_path = os.path.join(RESOURCES_FOLDER, selected_jpg)
    else:
        # 使用商品信息中的图片路径
        downloaded_images = product_info['downloaded_images']
        if not downloaded_images:
            print("错误: 商品信息中没有图片。")
            return
        
        print("\n可用的商品图片:")
        for i, img_info in enumerate(downloaded_images):
            print(f"{i+1}. {os.path.basename(img_info['path'])}")

        while True:
            try:
                choice = int(input("\n请选择要处理的商品图片序号: ")) - 1
                if 0 <= choice < len(downloaded_images):
                    jpg_path = downloaded_images[choice]['path']
                    break
                else:
                    print("无效的选择，请重试。")
            except ValueError:
                print("请输入数字序号。")

    # 检查对应的PNG文件是否存在
    png_path = jpg_path.replace('.jpg', '.png')
    if not os.path.exists(png_path):
        print(f"错误: 未找到对应的PNG文件 '{png_path}'")
        return

    # 调用图像描述API获取描述
    print("\n步骤 1: 获取图像描述...")
    describe_func_details = IDEOGRAM_FUNCTIONS_YUNWU["图像描述 (Describe)"]
    
    # 准备API调用数据
    with open(jpg_path, 'rb') as f:
        jpg_data = f.read()
    
    describe_files = {'image_file': ('image.jpg', jpg_data, 'image/jpeg')}
    describe_response = call_yunwu_api(api_key, "图像描述 (Describe)", describe_func_details, {}, describe_files, is_describe_call=True)
    
    if not describe_response or 'description' not in describe_response:
        print("错误: 无法获取图像描述。")
        return

    # 获取描述文本
    description = describe_response['description']
    print(f"获取到的描述: {description}")

    # 如果有商品信息，使用它来增强描述
    if product_info:
        # 添加商品标题和描述到提示词中
        title = product_info.get('title', '')
        product_desc = product_info.get('description', '')
        
        enhanced_description = f"{description}\n商品标题: {title}"
        if product_desc and product_desc != "未获取到":
            # 提取描述中的关键信息（限制长度）
            max_desc_length = 200
            if len(product_desc) > max_desc_length:
                product_desc = product_desc[:max_desc_length] + "..."
            enhanced_description += f"\n商品描述: {product_desc}"
        
        description = enhanced_description
        print(f"增强后的描述: {description}")

    # 准备编辑API调用
    print("\n步骤 2: 开始图片编辑...")
    edit_func_details = IDEOGRAM_FUNCTIONS_YUNWU["图片编辑 (Edit V3)"]
    
    # 读取PNG文件
    with open(png_path, 'rb') as f:
        png_data = f.read()
    
    # 准备编辑参数
    edit_params = {
        'prompt': description,
        'image': ('image.png', png_data, 'image/png')
    }
    
    # 执行编辑API调用
    _execute_edit_api_call(edit_params)

def extract_selling_points_from_page(page):
    """从详情页提取商品卖点信息，包括文字和图片形式的卖点"""
    selling_points = {
        'text_points': [],  # 文字形式的卖点
        'image_points': [], # 图片形式的卖点
        'specifications': {},# 商品规格参数
        'features': []      # 商品特点
    }
    
    try:
        # 1. 提取规格参数表
        spec_rows = page.query_selector_all('.od-pc-attribute-item')
        for row in spec_rows:
            try:
                key = row.query_selector('.od-pc-attribute-item-key')
                value = row.query_selector('.od-pc-attribute-item-val')
                if key and value:
                    key_text = key.text_content().strip().rstrip('：:')
                    value_text = value.text_content().strip()
                    if key_text and value_text:
                        selling_points['specifications'][key_text] = value_text
            except Exception as e:
                print(f"提取规格参数时出错: {e}")
        
        # 2. 提取详情页中的文字卖点
        # 尝试多个可能的选择器
        selectors = [
            '.detail-desc-decorate-richtext',  # 富文本描述
            '.desc-lazyload-container',       # 懒加载容器
            '.detail-desc-decorate-content'   # 装饰内容
        ]
        
        for selector in selectors:
            elements = page.query_selector_all(selector)
            for element in elements:
                try:
                    text = element.text_content().strip()
                    if text:
                        # 分析文本内容
                        lines = text.split('\n')
                        for line in lines:
                            line = line.strip()
                            # 识别可能的卖点（包含特定关键词或符合特定格式）
                            if any(keyword in line for keyword in ['特点', '优点', '功能', '适用', '优势', '特色', '特征']):
                                if 10 < len(line) < 200:  # 合理的卖点长度
                                    selling_points['text_points'].append(line)
                            # 识别可能的特点描述
                            elif len(line) > 10 and not any(skip in line.lower() for skip in ['联系', '咨询', '价格', '¥', '$', '电话']):
                                selling_points['features'].append(line)
                except Exception as e:
                    print(f"提取文字卖点时出错: {e}")
        
        # 3. 提取详情页中的图片卖点
        # 查找详情页中的图片
        detail_images = page.query_selector_all('.detail-desc-decorate-richtext img')
        for img in detail_images:
            try:
                src = img.get_attribute('src')
                alt = img.get_attribute('alt') or ''
                if src:
                    # 处理图片URL
                    if src.startswith('//'):
                        src = 'https:' + src
                    # 记录图片信息
                    selling_points['image_points'].append({
                        'url': src,
                        'alt': alt,
                        'context': extract_image_context(img)  # 提取图片周围的文本
                    })
            except Exception as e:
                print(f"提取图片卖点时出错: {e}")
        
        # 4. 清理和去重
        selling_points['text_points'] = list(set(selling_points['text_points']))
        selling_points['features'] = list(set(selling_points['features']))
        
        return selling_points
    except Exception as e:
        print(f"提取卖点信息时出错: {e}")
        return selling_points

def extract_image_context(img_element):
    """提取图片周围的相关文本内容"""
    context = []
    try:
        # 获取图片的父元素
        parent = img_element.evaluate('node => node.parentElement')
        if parent:
            # 获取前后的文本节点
            prev_text = parent.evaluate('node => node.previousSibling?.textContent || ""')
            next_text = parent.evaluate('node => node.nextSibling?.textContent || ""')
            
            # 清理文本
            for text in [prev_text, next_text]:
                if text:
                    text = text.strip()
                    if len(text) > 5:  # 忽略太短的文本
                        context.append(text)
    except Exception:
        pass
    return context

def generate_product_prompt(product_info, selling_points, image_index=0):
    """根据商品信息和卖点生成图片生成提示词"""
    prompt_elements = []
    
    # 1. 添加基本商品信息
    if product_info.get('title'):
        prompt_elements.append(f"Product: {product_info['title']}.")
    
    # 2. 添加规格参数中的关键信息
    specs = selling_points.get('specifications', {})
    important_specs = ['尺寸', '规格', '材质', '型号', 'Size', 'Material', 'Model']
    for key in important_specs:
        if key in specs:
            prompt_elements.append(f"{key}: {specs[key]}.")
    
    # 3. 添加文字卖点（轮流使用不同的卖点）
    text_points = selling_points.get('text_points', [])
    if text_points:
        point_index = image_index % len(text_points)
        prompt_elements.append(f"Key selling point: {text_points[point_index]}.")
    
    # 4. 添加特点（轮流使用不同的特点）
    features = selling_points.get('features', [])
    if features:
        feature_index = image_index % len(features)
        prompt_elements.append(f"Feature to highlight: {features[feature_index]}.")
    
    # 5. 添加视觉风格要求
    prompt_elements.append("Visual style: Ultra-realistic product photography, sharp focus, intricate details, professional studio lighting, clean background unless contextually relevant.")
    
    # 6. 添加构图要求
    prompt_elements.append("Composition: Dynamic angle if appropriate, or standard e-commerce shot. Highlight key product attributes visible in this specific image.")
    
    # 7. 添加商业效果要求
    prompt_elements.append("Impression: Commercial-grade, highly attractive, enticing for online shoppers.")
    
    # 8. 添加文本要求
    prompt_elements.append("Ensure all text in the generated image is in English, legible, and contextually correct if any text is part of the product design.")
    
    return " ".join(prompt_elements)

def get_alibaba_product_info_and_generate_prompt_for_edit(api_key):
    """从阿里巴巴商品页面获取信息并生成图片编辑提示词。
    使用标准Playwright库而不是MCP服务。
    为每张图片生成单独的提示词。"""
    alibaba_url = input("请输入阿里巴巴商品页面的URL，或直接回车跳过: ").strip()
    if not alibaba_url:
        print("用户未提供阿里巴巴URL，跳过此步骤。")
        return None

    print(f"准备从以下URL获取商品信息: {alibaba_url}")

    if not PLAYWRIGHT_AVAILABLE:
        print("错误: Playwright库未安装，无法获取阿里巴巴商品信息。")
        print("您可以使用pip安装: pip install playwright")
        print("然后安装浏览器驱动: playwright install")
        return None

    # 默认设置为显示浏览器
    show_browser = True
    print("将使用可见浏览器模式，以避免验证码问题。请在需要时手动处理验证码。")

    product_title = None
    product_features = []
    product_description = ""
    downloaded_image_paths_summary = []
    price_info = None
    image_sources = [] # 存储图片URL和alt信息
    all_results = [] # 存储每张图片的提示词和路径

    try:
        print("\n步骤 1: 启动Playwright浏览器并导航到阿里巴巴商品页面...")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not show_browser)
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
            )
            page = context.new_page()
            
            try:
                print("正在访问商品页面...")
                page.goto(alibaba_url, wait_until='networkidle', timeout=60000)
                
                if handle_slider_verification(page):
                    print("验证完成，继续获取商品信息...")
                
                # 等待页面加载完成
                page.wait_for_load_state('networkidle')
                time.sleep(3)
                
                print("开始获取商品信息...")
                
                # 获取商品标题
                title = page.locator('.title-first-column .title-text').first.text_content().strip()
                product_title = title
                print(f"标题获取成功: {title}")
                
                # 获取价格
                price = get_price_from_page(page)
                print(f"价格信息: {price}")
                
                # 获取商品描述
                description = get_description_from_page(page)
                if description != "未获取到":
                    print("描述获取成功")
                    product_description = description
                    # 从描述中提取产品特点
                    features = extract_features_from_description(description)
                    if features:
                        product_features.extend(features)
                        print(f"从描述中提取了 {len(features)} 个产品特点")
                else:
                    print("未获取到商品描述")

                # 获取商品图片
                try:
                    print("\n开始获取商品图片...")
                    # 等待图片容器加载
                    page.wait_for_selector('.detail-gallery-turn-wrapper img', timeout=10000)
                    
                    # 获取所有图片元素
                    image_elements = page.query_selector_all('.detail-gallery-turn-wrapper img')
                    
                    if not image_elements:
                        print("未找到商品图片")
                        return None
                    
                    print(f"找到 {len(image_elements)} 张商品图片")
                    
                    # 创建保存图片的文件夹
                    os.makedirs(RESOURCES_FOLDER, exist_ok=True)
                    
                    # 生成基础文件名
                    short_product_name = "alibaba_product"
                    if product_title:
                        words = product_title.split()[:3]
                        short_product_name = "_".join(words).lower()
                        short_product_name = "".join(c if c.isalnum() or c == '_' else '' for c in short_product_name)
                        if not short_product_name:
                            short_product_name = "alibaba_product"
                    
                    # 下载图片并生成提示词
                    for i, img in enumerate(image_elements):
                        try:
                            # 获取图片URL
                            img_url = img.get_attribute('src')
                            if not img_url:
                                continue
                            
                            # 处理图片URL
                            if img_url.startswith('//'):
                                img_url = 'https:' + img_url
                            
                            # 获取大图URL
                            img_url = img_url.replace('50x50', '800x800')
                            
                            # 下载图片
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            img_filename = f"{short_product_name}_{i+1}_{timestamp}.jpg"
                            img_path = os.path.join(RESOURCES_FOLDER, img_filename)
                            
                            print(f"正在下载图片 {i+1}: {img_url}")
                            img_response = requests.get(img_url, timeout=20)
                            
                            if img_response.status_code == 200:
                                with open(img_path, 'wb') as f:
                                    f.write(img_response.content)
                                print(f"图片已保存到: {img_path}")
                                downloaded_image_paths_summary.append({
                                    'path': img_path,
                                    'url': img_url,
                                    'alt': img.get_attribute('alt') or ''
                                })

                                # 为每张图片生成特定的提示词
                                prompt_elements = []
                                
                                # 添加商品标题
                                if product_title:
                                    prompt_elements.append(f"Product: {product_title}.")
                                
                                # 添加产品特点(每张图片突出一个不同的特点)
                                if product_features:
                                    feature_index = i % len(product_features)
                                    current_feature = product_features[feature_index]
                                    prompt_elements.append(f"KEY FEATURE TO HIGHLIGHT IN THIS IMAGE: {current_feature.strip().rstrip('.')}.")
                                
                                # 添加图片alt文本
                                alt_text = img.get_attribute('alt')
                                if alt_text:
                                    prompt_elements.append(f"Image details: {alt_text}.")
                                
                                # 添加视觉风格要求
                                prompt_elements.append("Visual style: Ultra-realistic product photography, sharp focus, intricate details, professional studio lighting, clean background unless contextually relevant.")
                                
                                # 添加构图要求
                                prompt_elements.append("Composition: Dynamic angle if appropriate, or standard e-commerce shot. Highlight key product attributes visible in this specific image.")
                                
                                # 添加商业效果要求
                                prompt_elements.append("Impression: Commercial-grade, highly attractive, enticing for online shoppers.")
                                
                                # 添加文本要求
                                prompt_elements.append("Ensure all text in the generated image is in English, legible, and contextually correct if any text is part of the product design.")
                                
                                # 组合提示词
                                specific_prompt = " ".join(prompt_elements)
                                print(f"为图片 {os.path.basename(img_path)} 生成的特定提示词 (部分): {specific_prompt[:120]}...")
                                
                                # 保存提示词和图片路径
                                all_results.append({
                                    "prompt": specific_prompt,
                                    "reference_image": img_path
                                })
                            else:
                                print(f"下载图片失败，HTTP状态码: {img_response.status_code}")
                        except Exception as e:
                            print(f"下载图片 {i+1} 时出错: {str(e)}")
                            continue
                    
                    print(f"\n总共成功下载了 {len(downloaded_image_paths_summary)} 张图片")
                    
                except Exception as e:
                    print(f"获取商品图片时出错: {str(e)}")
                
            except Exception as e:
                print(f"获取商品信息时出错: {str(e)}")
                return None
            finally:
                browser.close()
        
        # 将生成的提示词保存到1.txt文件
        if all_results:
            try:
                with open("1.txt", "w", encoding="utf-8") as f:
                    # 首先写入商品基本信息和卖点总结
                    f.write("===== 商品信息总结 =====\n")
                    if product_title:
                        f.write(f"商品标题: {product_title}\n")
                    if price_info:
                        f.write(f"价格信息: {price_info}\n")
                    if selling_points:
                        f.write("\n规格参数:\n")
                        for key, value in selling_points['specifications'].items():
                            f.write(f"- {key}: {value}\n")
                        
                        f.write("\n主要卖点:\n")
                        for point in selling_points['text_points']:
                            f.write(f"- {point}\n")
                        
                        f.write("\n商品特点:\n")
                        for feature in selling_points['features']:
                            f.write(f"- {feature}\n")
                        
                        if selling_points['image_points']:
                            f.write("\n详情页图片卖点:\n")
                            for img_point in selling_points['image_points']:
                                f.write(f"- 图片描述: {img_point['alt']}\n")
                                if img_point['context']:
                                    f.write(f"  相关文本: {' | '.join(img_point['context'])}\n")
                    f.write("\n")
                    
                    # 然后写入每张图片的提示词
                    for i, result in enumerate(all_results):
                        f.write(f"\n===== 图片 {i+1} 提示词 =====\n")
                        f.write(result["prompt"] + "\n")
                print(f"已将所有提示词和商品信息保存到 1.txt 文件")
            except Exception as e:
                print(f"保存提示词到文件时出错: {e}")
        
        # 如果成功获取了图片，调用图片编辑API
        if downloaded_image_paths_summary:
            print("\n步骤 3: 开始处理下载的图片...")
            
            # 构建商品信息
            product_info = {
                'title': product_title,
                'description': product_description,
                'price': price_info,
                'downloaded_images': downloaded_image_paths_summary
            }
            
            # 提取商品卖点信息
            print("\n开始提取商品卖点信息...")
            selling_points = extract_selling_points_from_page(page)
            if selling_points:
                print(f"成功提取到 {len(selling_points['text_points'])} 个文字卖点")
                print(f"成功提取到 {len(selling_points['image_points'])} 个图片卖点")
                print(f"成功提取到 {len(selling_points['specifications'])} 个规格参数")
                print(f"成功提取到 {len(selling_points['features'])} 个商品特点")
            
            # 生成特定的提示词
            product_info = {
                'title': product_title,
                'description': product_description,
                'price': price_info
            }
            
            specific_prompt = generate_product_prompt(product_info, selling_points, i)
            
            # 调用图片编辑API
            process_describe_and_edit_image(api_key, product_info=product_info)
            return product_info
        
    except Exception as e:
        print(f"处理阿里巴巴信息时发生严重错误: {e}")
        import traceback
        traceback.print_exc()
        return None

def extract_features_from_description(description):
    """从商品描述中提取产品特点"""
    features = []
    
    # 按句号或换行符分割描述
    sentences = re.split(r'[。\n]', description)
    
    for sentence in sentences:
        # 清理句子
        sentence = sentence.strip()
        if len(sentence) > 10 and len(sentence) < 100:  # 合适的句子长度
            # 过滤掉不太可能是产品特点的句子
            if not any(skip in sentence.lower() for skip in ['联系', '咨询', '价格', '¥', '$', '电话', 'qq', '微信']):
                features.append(sentence)
    
    # 限制特点数量
    return features[:5]  # 最多返回5个特点

def handle_slider_verification(page):
    """
    处理阿里巴巴的滑块验证码
    """
    try:
        # 检查是否存在滑块验证码
        slider = page.locator("//span[contains(text(), '请按住滑块')]")
        if slider.is_visible():
            print("检测到滑块验证码，等待30秒进行人工验证...")
            # 给用户30秒时间手动完成验证
            time.sleep(30)
            return True
    except:
        pass
    return False

def get_price_from_page(page):
    """
    从页面获取价格信息
    """
    try:
        # 等待价格相关元素加载
        page.wait_for_selector('[class*="price"]', timeout=5000)
        
        # 执行JavaScript来获取价格
        price_info = page.evaluate('''() => {
            function extractPrice(element) {
                const text = element.textContent.trim();
                if (text.includes('¥') || text.includes('￥')) {
                    return text;
                }
                return null;
            }
            
            // 尝试获取价格区间
            const priceElements = document.querySelectorAll('[class*="price"]');
            for (const el of priceElements) {
                const price = extractPrice(el);
                if (price) {
                    return price;
                }
            }
            
            // 尝试获取优惠价格
            const discountElements = document.querySelectorAll('[class*="discount"]');
            for (const el of discountElements) {
                const price = extractPrice(el);
                if (price) {
                    return price;
                }
            }
            
            return null;
        }''')
        
        if price_info:
            print(f"JavaScript提取到价格: {price_info}")
            return clean_price(price_info)
            
        # 如果JavaScript方法失败，尝试直接获取元素
        price_selectors = [
            '.price-content',
            '.price',
            '[class*="price-now"]',
            '[class*="price-original"]'
        ]
        
        for selector in price_selectors:
            try:
                element = page.locator(selector).first
                if element:
                    text = element.text_content().strip()
                    if '¥' in text or '￥' in text:
                        print(f"选择器 {selector} 提取到价格: {text}")
                        return clean_price(text)
            except:
                continue
                
        return "未获取到"
    except Exception as e:
        print(f"获取价格时出错: {str(e)}")
        return "未获取到"

def get_description_from_page(page):
    """
    获取商品描述信息和卖点
    """
    try:
        # 尝试点击"商品详情"标签
        desc_selectors = [
            'text=商品详情',
            '[data-tab-key="descriptionTab"]',
            '#detailTab',
            '.detail-tab-trigger'
        ]
        
        for selector in desc_selectors:
            try:
                tab = page.locator(selector).first
                if tab and tab.is_visible():
                    tab.click()
                    print("成功点击商品详情标签")
                    break
            except:
                continue
        
        # 等待描述内容加载
        time.sleep(3)
        
        # 使用JavaScript获取卖点和描述内容
        description = page.evaluate('''() => {
            function getTextContent(element) {
                return element ? element.textContent.trim() : null;
            }
            
            // 尝试获取卖点信息
            let selling_points = [];
            const selling_point_selectors = [
                '.offer-attr-list',
                '.offer-attr',
                '.offer-detail-content-list',
                '.offer-detail-content',
                '.offer-attr-item'
            ];
            
            for (const selector of selling_point_selectors) {
                const elements = document.querySelectorAll(selector);
                for (const el of elements) {
                    const text = getTextContent(el);
                    if (text && text.length > 0) {
                        selling_points.push(text);
                    }
                }
            }
            
            // 尝试获取详细描述
            const desc_selectors = [
                '.detail-desc-content',
                '.description-content',
                '#J_DetailDesc',
                '.desc-content',
                '[class*="description"]',
                '[class*="detail"]'
            ];
            
            let description = null;
            for (const selector of desc_selectors) {
                const element = document.querySelector(selector);
                const text = getTextContent(element);
                if (text && text.length > 50) {  // 确保内容足够长
                    description = text;
                    break;
                }
            }
            
            // 如果没有找到描述，尝试获取所有可能的描述内容
            if (!description) {
                const allDescElements = document.querySelectorAll('[class*="desc"], [class*="detail"]');
                for (const el of allDescElements) {
                    const text = getTextContent(el);
                    if (text && text.length > 50) {
                        description = text;
                        break;
                    }
                }
            }
            
            return {
                selling_points: selling_points,
                description: description
            };
        }''')
        
        if description and description.get('selling_points'):
            selling_points = description['selling_points']
            desc = description.get('description', '')
            
            # 组合卖点和描述
            combined_text = "商品卖点:\n" + "\n".join(selling_points)
            if desc:
                combined_text += "\n\n商品描述:\n" + desc
            
            return combined_text
            
        # 如果JavaScript方法失败，尝试直接获取元素
        selling_point_selectors = [
            '.offer-attr-list',
            '.offer-attr',
            '.offer-detail-content-list',
            '.offer-detail-content',
            '.offer-attr-item'
        ]
        
        selling_points = []
        for selector in selling_point_selectors:
            try:
                elements = page.locator(selector).all()
                for element in elements:
                    text = element.text_content().strip()
                    if text:
                        selling_points.append(text)
            except:
                continue
        
        desc_content_selectors = [
            '.detail-desc-content',
            '.description-content',
            '#J_DetailDesc',
            '.desc-content',
            '[class*="description"]',
            '[class*="detail"]'
        ]
        
        description = None
        for selector in desc_content_selectors:
            try:
                content = page.locator(selector).first
                if content:
                    text = content.text_content().strip()
                    if text and len(text) > 50:  # 确保内容足够长
                        description = text
                        break
            except:
                continue
        
        if selling_points:
            combined_text = "商品卖点:\n" + "\n".join(selling_points)
            if description:
                combined_text += "\n\n商品描述:\n" + description
            return combined_text
        elif description:
            return description
        
        return "未获取到"
    except Exception as e:
        print(f"获取描述时出错: {str(e)}")
        return "未获取到"

def clean_price(price_text):
    """
    清理并格式化价格文本
    """
    if not price_text or price_text == "未获取到":
        return "未获取到"
    
    # 使用正则表达式提取价格范围
    price_pattern = r'¥(\d+\.?\d*)'
    matches = re.findall(price_pattern, price_text)
    
    if matches:
        if len(matches) >= 2:
            return f"¥{matches[0]} - ¥{matches[-1]}"
        else:
            return f"¥{matches[0]}"
    return price_text

def main():
    line_separator = "=" * 50 
    print(f"\n{line_separator}")
    print("--- edotfish 图像处理软件 ---") 
    print(f"{line_separator}\n")
    create_folders()
    api_key = get_api_key()
    while True:
        display_and_select_function(api_key)
        
        cont = input("\n是否要使用其他功能? (y/n): ").strip().lower()
        if cont != 'y':
            break
    print("程序结束。")

if __name__ == "__main__":
    main() 