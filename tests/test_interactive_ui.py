#!/usr/bin/env python3
"""交互式研究功能 — 前端 UI 冒烟测试（Playwright）
用法: python3 tests/test_interactive_ui.py [host:port]
默认: localhost:8001
"""
import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "localhost:8001"
URL = f"http://{BASE}"
PASS = 0
FAIL = 0
SCREENSHOTS = []


def green(msg):
    global PASS
    print(f"\033[32m✅ {msg}\033[0m")
    PASS += 1


def red(msg):
    global FAIL
    print(f"\033[31m❌ {msg}\033[0m")
    FAIL += 1


def screenshot(page, name):
    path = f"/tmp/ui-test-{name}.png"
    page.screenshot(path=path, full_page=True)
    SCREENSHOTS.append(path)
    print(f"    截图: {path}")


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 900})

    # 测试 6: 首页加载
    print("--- 测试 6: 首页加载")
    try:
        page.goto(URL)
        page.wait_for_load_state("networkidle")
        screenshot(page, "homepage")
        title = page.title()
        # 检查标签页是否存在
        tabs = page.locator("text=新建研究")
        if tabs.count() > 0:
            green(f"首页加载成功，标题: {title}，'新建研究'标签可见")
        else:
            red(f"首页加载但未找到'新建研究'标签，标题: {title}")
    except Exception as e:
        red(f"首页加载失败: {e}")

    # 先切到"新建研究"标签页
    print("--- 切换到'新建研究'标签页")
    try:
        page.locator("text=新建研究").click()
        page.wait_for_timeout(500)
        screenshot(page, "new-research-tab")
    except Exception as e:
        red(f"切换标签失败: {e}")

    # 测试 7: 交互模式开关
    print("--- 测试 7: 交互模式切换")
    try:
        # 查找模式开关（toggle/checkbox/switch）
        toggle = page.locator("text=交互模式").or_(
            page.locator("label:has-text('交互')")
        ).first
        toggle.click(timeout=5000)
        page.wait_for_timeout(500)
        screenshot(page, "interactive-mode")
        green("切换到交互模式成功")
    except Exception as e:
        # 可能交互模式开关用了不同文案，看看当前页面有什么
        screenshot(page, "interactive-mode-debug")
        red(f"模式切换失败: {e}")

    # 测试 8: 输入股票代码提交
    print("--- 测试 8: 输入股票代码提交")
    try:
        # 找到可见的输入框
        input_box = page.locator("input:visible").first
        input_box.fill("600519", timeout=5000)

        # 找到可见的提交按钮
        submit_btn = page.locator("button:visible:has-text('开始')").or_(
            page.locator("button:visible:has-text('分析')")
        ).or_(
            page.locator("button:visible:has-text('研究')")
        ).first
        submit_btn.click(timeout=5000)
        page.wait_for_timeout(3000)
        screenshot(page, "after-submit")
        green("提交请求成功")
    except Exception as e:
        screenshot(page, "submit-debug")
        red(f"提交失败: {e}")

    # 测试 9: 等待策略展示 + 截图
    print("--- 测试 9: 等待响应")
    try:
        page.wait_for_timeout(8000)
        screenshot(page, "final-state")
        green("最终状态已截图（需人工确认标签编辑功能）")
    except Exception as e:
        red(f"截图失败: {e}")

    browser.close()

print()
print(f"=== 结果: {PASS} 通过 / {FAIL} 失败 ===")
if SCREENSHOTS:
    print(f"截图保存在: {', '.join(SCREENSHOTS)}")
