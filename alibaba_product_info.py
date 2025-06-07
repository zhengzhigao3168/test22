import os
import re
import json
import random
import time
import urllib.parse
from datetime import datetime
import requests
from playwright.sync_api import sync_playwright, TimeoutError

# 常量定义
RESOURCES_FOLDER = os.path.join(os.path.dirname(__file__), "素材")
TEST_URL = "https://detail.1688.com/offer/734144859963.html?spm=a26352.13672862.offerlist.19.56ee1e62YCKWHy&cosite=-&tracelog=p4p&_p_isad=1&clickid=08ffd176ef94448d88e296da65948b97&sessionid=c712dcf2ae99c797703abe1c92c7ca75"

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
    获取商品描述信息
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
        
        # 使用JavaScript获取描述内容
        description = page.evaluate('''() => {
            function getTextContent(element) {
                return element ? element.textContent.trim() : null;
            }
            
            // 尝试获取详细描述
            const selectors = [
                '.detail-desc-content',
                '.description-content',
                '#J_DetailDesc',
                '.desc-content',
                '[class*="description"]',
                '[class*="detail"]'
            ];
            
            for (const selector of selectors) {
                const element = document.querySelector(selector);
                const text = getTextContent(element);
                if (text && text.length > 50) {  // 确保内容足够长
                    return text;
                }
            }
            
            // 尝试获取所有可能的描述内容
            const allDescElements = document.querySelectorAll('[class*="desc"], [class*="detail"]');
            for (const el of allDescElements) {
                const text = getTextContent(el);
                if (text && text.length > 50) {
                    return text;
                }
            }
            
            return null;
        }''')
        
        if description:
            return description
            
        # 如果JavaScript方法失败，尝试直接获取元素
        desc_content_selectors = [
            '.detail-desc-content',
            '.description-content',
            '#J_DetailDesc',
            '.desc-content',
            '[class*="description"]',
            '[class*="detail"]'
        ]
        
        for selector in desc_content_selectors:
            try:
                content = page.locator(selector).first
                if content:
                    text = content.text_content().strip()
                    if text and len(text) > 50:  # 确保内容足够长
                        return text
            except:
                continue
        
        return "未获取到"
    except Exception as e:
        print(f"获取描述时出错: {str(e)}")
        return "未获取到"

def get_alibaba_product_info(url, show_browser=True):
    """
    使用Playwright获取阿里巴巴商品信息
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not show_browser)
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
        )
        page = context.new_page()
        
        try:
            print("正在访问商品页面...")
            page.goto(url, wait_until='networkidle', timeout=60000)
            
            if handle_slider_verification(page):
                print("验证完成，继续获取商品信息...")
            
            # 等待页面加载完成
            page.wait_for_load_state('networkidle')
            time.sleep(3)
            
            print("开始获取商品信息...")
            
            # 获取商品标题
            title = page.locator('.title-first-column .title-text').first.text_content().strip()
            print(f"标题获取成功: {title}")
            
            # 获取价格
            price = get_price_from_page(page)
            print(f"价格信息: {price}")
            
            # 获取商品描述
            description = get_description_from_page(page)
            if description != "未获取到":
                print("描述获取成功")
            else:
                print("描述获取失败")
            
            # 获取商品图片
            image_urls = []
            try:
                # 等待图片加载
                page.wait_for_selector('.detail-gallery-img', timeout=5000)
                images = page.locator('.detail-gallery-img').all()
                for img in images:
                    src = img.get_attribute('src') or img.get_attribute('data-src')
                    if src:
                        if src.startswith("//"):
                            src = "https:" + src
                        if src not in image_urls:
                            image_urls.append(src)
                print(f"图片URL获取成功: {len(image_urls)} 张")
            except Exception as e:
                print(f"获取图片时出错: {str(e)}")
            
            result = {
                'title': title,
                'price': price,
                'description': description,
                'images': image_urls
            }
            
            # 打印获取到的信息
            print("\n获取到的商品信息：")
            print(f"标题: {result['title']}")
            print(f"价格: {result['price']}")
            print(f"描述: {result['description'][:200]}..." if result['description'] != "未获取到" else "描述: 未获取到")
            print(f"图片数量: {len(result['images'])}")
            
            try:
                # 创建调试目录（如果不存在）
                debug_dir = os.path.join(os.path.dirname(__file__), "debug")
                os.makedirs(debug_dir, exist_ok=True)
                
                # 保存页面快照
                snapshot_path = os.path.join(debug_dir, "debug_snapshot.png")
                page.screenshot(path=snapshot_path, timeout=5000)
                print(f"\n已保存页面快照到 {snapshot_path}")
            except Exception as e:
                print(f"保存快照时出错: {str(e)}")
            
            return result
            
        except Exception as e:
            print(f"获取商品信息时出错: {str(e)}")
            return None
        finally:
            browser.close()

def main():
    # 使用测试URL
    print(f"使用测试URL: {TEST_URL}")
    product_info = get_alibaba_product_info(TEST_URL)
    if not product_info:
        print("获取商品信息失败")

if __name__ == "__main__":
    main() 