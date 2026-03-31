"""Unified example that submits one task and polls until completion."""

import os
import sys
import time

import httpx

BASE_URL = os.getenv("SUNO_API_BASE_URL", "http://207.180.218.216:8005/api")
POLL_INTERVAL_SECONDS = 5
TRANSIENT_POLL_STATUS_CODES = {502, 503, 504}
MAX_CONSECUTIVE_POLL_ERRORS = 5


def extract_error_message(resp: httpx.Response) -> str:
    try:
        data = resp.json()
    except Exception:
        text = (resp.text or "").strip()
        if text:
            return text[:300]
        return f"HTTP {resp.status_code}"

    if isinstance(data, dict):
        return str(data.get("detail") or data.get("error") or data)
    return str(data)


def create_task():
    payload = {
        # 必填。
        # is_custom=False 时：这里传“歌曲描述”。
        # is_custom=True  时：这里传“歌词内容”。
        "prompt": "A peaceful acoustic guitar melody for reading",

        # 可选。只在 is_custom=True 时有明显作用。
        # 用来指定风格、乐器、男女声等，例如：
        # "pop, female vocal, acoustic, emotional"
        "tags": None,

        # 可选。只在 is_custom=True 时有明显作用。
        # 生成歌曲的标题。
        "title": None,

        # 可选。True 表示纯音乐，False 表示允许人声。
        "make_instrumental": True,

        # 必填。
        # False: 简单描述模式，prompt 是歌曲描述。
        # True:  自定义模式，prompt 是歌词，tags/title 会参与生成。
        "is_custom": False,

        # 可选。模型版本，不传时后端默认 chirp-v3.5。
        # 常见可用值：v3.5、v4、v4.5、v5、v5.5
        "model": "v4",
    }

    print("🚀 正在请求生成...")
    print(f"   BASE_URL: {BASE_URL}")
    print(f"   model: {payload['model']}")
    print(f"   is_custom: {payload['is_custom']}")
    print(f"   make_instrumental: {payload['make_instrumental']}")

    resp = httpx.post(f"{BASE_URL}/tasks", json=payload, timeout=30.0)
    if resp.is_error:
        message = extract_error_message(resp)
        print(f"❌ 提交失败（HTTP {resp.status_code}）: {message}")
        sys.exit(1)

    task_id = resp.json()["task_id"]
    print(f"✅ 任务已提交，ID: {task_id}")
    return task_id


def poll_task(task_id):
    print("⏳ 正在查询生成进度...")
    start_time = time.time()
    consecutive_errors = 0

    while True:
        try:
            resp = httpx.get(f"{BASE_URL}/tasks/{task_id}", timeout=30.0)
        except httpx.HTTPError as exc:
            consecutive_errors += 1
            if consecutive_errors >= MAX_CONSECUTIVE_POLL_ERRORS:
                print(f"❌ 查询失败: {exc}")
                return
            print(f"⚠️ 查询异常，准备重试（{consecutive_errors}/{MAX_CONSECUTIVE_POLL_ERRORS}）: {exc}")
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        if resp.is_error:
            message = extract_error_message(resp)
            if resp.status_code in TRANSIENT_POLL_STATUS_CODES:
                consecutive_errors += 1
                if consecutive_errors >= MAX_CONSECUTIVE_POLL_ERRORS:
                    print(f"❌ 查询失败（HTTP {resp.status_code}）: {message}")
                    return
                print(
                    f"⚠️ 查询遇到临时错误（HTTP {resp.status_code}），"
                    f"准备重试（{consecutive_errors}/{MAX_CONSECUTIVE_POLL_ERRORS}）: {message}"
                )
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            print(f"❌ 查询失败（HTTP {resp.status_code}）: {message}")
            return

        consecutive_errors = 0

        data = resp.json()
        status = data["status"]
        elapsed = int(time.time() - start_time)

        if status == "success":
            print(f"🎉 生成成功! 总耗时约 {elapsed} 秒")
            result = data.get("result") or {}
            for i, url in enumerate(result.get("song_url_list", []), 1):
                print(f"   [{i}] {url}")
            return

        if status == "failed":
            print(f"❌ 生成失败（约 {elapsed} 秒）: {data.get('error')}")
            return

        print(f"   当前状态: {status}，已等待 {elapsed} 秒")
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    tid = create_task()
    poll_task(tid)
