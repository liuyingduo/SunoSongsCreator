"""使用简单模式（Simple Mode）生成音乐的示例。"""

import time

import httpx

BASE_URL = "http://207.180.218.216:8005/api"
POLL_INTERVAL_SECONDS = 5


def create_simple_task():
    # 只需要传入描述内容，可选是否纯音乐。
    payload = {
        "prompt": "A peaceful acoustic guitar melody for reading",
        "make_instrumental": True,
        "is_custom": False,
    }

    print(f"🚀 [简单模式] 正在请求生成: '{payload['prompt']}'")
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
    tid = create_simple_task()
    if tid:
        poll_task(tid)
