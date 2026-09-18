"""Open one confirmed application kit and fill only unambiguous basics.

This script intentionally never presses a submit button. CAPTCHA, login,
subjective questions and all final submissions remain user-controlled.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
DB_PATH = ROOT / "data" / "radar.db"
CONFIG_PATH = ROOT / "config" / "application.json"
SCREENSHOT_PATH = ROOT / "data" / "applications"


def load_kit(kit_id: int) -> sqlite3.Row:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        kit = conn.execute("""
          SELECT k.*, j.title, j.company, j.url, r.stored_path, r.filename
          FROM application_kits k JOIN jobs j ON j.id = k.job_id JOIN resumes r ON r.id = k.resume_id
          WHERE k.id = ?
        """, (kit_id,)).fetchone()
    finally:
        conn.close()
    if not kit:
        raise SystemExit("投递包不存在")
    if kit["status"] != "已准备":
        raise SystemExit("请先在网页中确认投递包，将状态设为“已准备”")
    return kit


def log_attempt(kit_id: int, result: str, note: str, screenshot: str = "") -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("INSERT INTO application_attempts(kit_id, started_at, finished_at, result, note, screenshot_path) VALUES (?, ?, ?, ?, ?, ?)", (kit_id, datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat(), result, note, screenshot))
        conn.commit()
    finally:
        conn.close()


async def fill_application(kit: sqlite3.Row, profile: dict[str, object]) -> None:
    try:
        from playwright.async_api import async_playwright
    except ImportError as error:
        raise SystemExit("请先执行 pip install -r requirements-apply.txt 和 playwright install chromium") from error

    SCREENSHOT_PATH.mkdir(parents=True, exist_ok=True)
    screenshot = SCREENSHOT_PATH / f"kit-{kit['id']}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=False)
        page = await browser.new_page()
        try:
            await page.goto(kit["url"], wait_until="domcontentloaded", timeout=45000)
            body = (await page.locator("body").inner_text()).lower()
            if any(word in body for word in ("captcha", "验证码", "安全验证", "人机验证")):
                await page.screenshot(path=str(screenshot), full_page=True)
                log_attempt(kit["id"], "需要人工处理", "检测到验证码或安全验证，未填写任何表单", str(screenshot.relative_to(ROOT)))
                print("检测到验证码或安全验证；请在浏览器中自行处理，脚本未填写表单。")
                input("处理完成后按 Enter 关闭浏览器…")
                return

            fields = {
                "full_name": ["input[name*='name' i]", "input[autocomplete='name']"],
                "email": ["input[type='email']", "input[name*='email' i]"],
                "phone": ["input[type='tel']", "input[name*='phone' i]", "input[name*='mobile' i]"],
                "city": ["input[name*='city' i]"],
            }
            filled = []
            for key, selectors in fields.items():
                value = str(profile.get(key, "")).strip()
                if not value:
                    continue
                for selector in selectors:
                    locator = page.locator(selector).first
                    if await locator.count() and await locator.is_visible():
                        await locator.fill(value)
                        filled.append(key)
                        break
            resume = Path(kit["stored_path"])
            if not resume.is_absolute():
                resume = ROOT / resume
            if resume.exists():
                upload = page.locator("input[type='file']").first
                if await upload.count():
                    await upload.set_input_files(str(resume))
                    filled.append("resume")
            await page.screenshot(path=str(screenshot), full_page=True)
            log_attempt(kit["id"], "等待确认", f"已填写：{'、'.join(filled) or '无'}；脚本不会点击提交", str(screenshot.relative_to(ROOT)))
            print(f"已填写：{'、'.join(filled) or '无'}。请核对全部内容，并由你亲自点击官网最终提交。")
            input("完成或取消后按 Enter 关闭浏览器…")
        finally:
            await browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="受控投递表单填充（不提交）")
    parser.add_argument("--kit", type=int, required=True, help="已准备投递包的编号")
    args = parser.parse_args()
    if not CONFIG_PATH.exists():
        raise SystemExit("请先复制 config/application.example.json 为 config/application.json 并填写真实资料")
    import asyncio
    asyncio.run(fill_application(load_kit(args.kit), json.loads(CONFIG_PATH.read_text(encoding="utf-8"))))


if __name__ == "__main__":
    main()
