"""使用自定义模式（Custom Mode）生成音乐的示例。"""

import time

import httpx

BASE_URL = "http://127.0.0.1:8005/api"
POLL_INTERVAL_SECONDS = 5


def create_custom_task():
    # 自定义模式下，prompt 为歌词，tags 为风格，title 为标题。
    # 支持的 model 参数包括：v2、v3、v3.5、v4、v4.5、v4.5+、v5、v5.5。
    payload = {
        "prompt": "[Verse 1]\n我在忙碌中停下来一点点\n[Chorus]\n让这一刻变得安静一点\n[Outro]\n结束了这一天",
        "tags": "pop, female voice, acoustic, emotional",
        "title": "忙碌中的安静",
        "is_custom": True,
        "model": "v3.5",
        "make_instrumental": False,
    }

    print(f"🚀 [自定义模式] 正在请求生成: '{payload['title']}'")
    resp = httpx.post(f"{BASE_URL}/tasks", json=payload, timeout=30.0)
    if not resp.is_success:
        print(f"❌ 提交失败: {resp.status_code} - {resp.text}")
        return None

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
            for i, url in enumerate(data["result"]["song_url_list"], 1):
                print(f"   [{i}] {url}")
            break

        if status == "failed":
            print(f"❌ 生成失败（约 {elapsed} 秒）: {data.get('error')}")
            break

        print(f"   当前状态: {status}，已等待 {elapsed} 秒")
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    tid = create_custom_task()
    if tid:
        poll_task(tid)
