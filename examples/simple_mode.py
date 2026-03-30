"""使用简单描述模式 (Simple Mode) 生成音乐的示例。"""
import httpx
import time

BASE_URL = "http://127.0.0.1:8005/api"

def create_simple_task():
    # 只需要描述内容，可以开启/关闭 纯背景音乐 (make_instrumental)
    payload = {
        "prompt": "A peaceful acoustic guitar melody for reading",
        "make_instrumental": True,
        "is_custom": False
    }
    
    print(f"🚀 [简单模式] 正在请求生成: '{payload['prompt']}'")
    resp = httpx.post(f"{BASE_URL}/tasks", json=payload)
    if resp.status_code != 201:
        print(f"❌ 提交失败: {resp.text}")
        return
    
    task_id = resp.json()["task_id"]
    print(f"✅ 任务已提交，ID: {task_id}")
    return task_id

def poll_task(task_id):
    print("⏳ 正在查询生成进度...")
    while True:
        resp = httpx.get(f"{BASE_URL}/tasks/{task_id}")
        data = resp.json()
        status = data["status"]
        
        if status == "success":
            print("\n🎉 生成成功!")
            for i, url in enumerate(data["result"]["song_url_list"], 1):
                print(f"   [{i}] {url}")
            break
        elif status == "failed":
            print(f"\n❌ 生成失败: {data.get('error')}")
            break
        else:
            print(f"   当前状态: {status}...", end="\r")
            time.sleep(5)

if __name__ == "__main__":
    tid = create_simple_task()
    if tid:
        poll_task(tid)
