"""使用定制模式 (Custom Mode) 生成音乐的示例。"""
import httpx
import time

BASE_URL = "http://127.0.0.1:8000/api"

def create_custom_task():
    # 定制模式：prompt 为歌词，tags 为风格，title 为标题
    # 支持的 model 参数包括: 
    # v2, v3, v3.5, v4, v4.5, v4.5+, v5, v5.5
    # 自定义 model 标识符也支持: chirp-v3-0, chirp-v3-5, chirp-v4, chirp-fenix 等
    payload = {
        "prompt": "[Verse 1]\n我在忙碌中停下来了点歌\n[Chorus]\n让这一刻变得安静...\n[Outro]\n结束了这一天...",
        "tags": "pop, female voice, acoustic, emotional",
        "title": "忙碌中的安静",
        "is_custom": True, 
        "model": "v3.5", # 尝试指定不同的模型版本
        "make_instrumental": False
    }
    
    print(f"🚀 [定制模式] 正在请求生成: '{payload['title']}'")
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
    tid = create_custom_task()
    if tid:
        poll_task(tid)
