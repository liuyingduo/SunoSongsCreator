"""统一示例：一个脚本覆盖所有常用字段。"""

import os
import time

import httpx

BASE_URL = os.getenv("SUNO_API_BASE_URL", "http://127.0.0.1:8005/api")
POLL_INTERVAL_SECONDS = 5


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
    resp.raise_for_status()

    task_id = resp.json()["task_id"]
    print(f"✅ 任务已提交，ID: {task_id}")
    return task_id


def poll_task(task_id):
    print("⏳ 正在查询生成进度...")
    start_time = time.time()

    while True:
        resp = httpx.get(f"{BASE_URL}/tasks/{task_id}", timeout=30.0)
        resp.raise_for_status()
        data = resp.json()
        status = data["status"]
        elapsed = int(time.time() - start_time)

        if status == "success":
            print(f"🎉 生成成功! 总耗时约 {elapsed} 秒")
            result = data.get("result") or {}
            for i, url in enumerate(result.get("song_url_list", []), 1):
                print(f"   [{i}] {url}")
            break

        if status == "failed":
            print(f"❌ 生成失败（约 {elapsed} 秒）: {data.get('error')}")
            break

        print(f"   当前状态: {status}，已等待 {elapsed} 秒")
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    tid = create_task()
    poll_task(tid)
