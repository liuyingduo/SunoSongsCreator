import time
import httpx
import sys

# API 基础地址（根据实际运行地址修改）
BASE_URL = "http://127.0.0.1:8000/api"

def test_generate_song(prompt: str):
    """
    测试流程：
    1. 发送 POST 请求创建生成任务
    2. 获取 task_id
    3. 循环请求 GET 接口查询状态，直到状态变为 success 或 failed
    4. 输出最终的音乐链接
    """
    
    print(f"🚀 正在请求生成音乐: '{prompt}'")
    
    # 步骤 1: 创建任务
    payload = {
        "prompt": prompt,
        "make_instrumental": False,
        "is_custom": False
    }
    
    try:
        response = httpx.post(f"{BASE_URL}/tasks", json=payload, timeout=10)
        response.raise_for_status()
    except Exception as e:
        print(f"❌ 创建任务失败: {e}")
        print("请确保 API 服务已启动 (uvicorn api.main:app)")
        return

    task = response.json()
    task_id = task["task_id"]
    print(f"✅ 任务已提交，ID: {task_id}")

    # 步骤 2: 轮询查询状态
    print("⏳ 正在排队并生成中，请稍候 (Suno 通常需要 1-2 分钟)...")
    
    start_time = time.time()
    while True:
        try:
            status_res = httpx.get(f"{BASE_URL}/tasks/{task_id}", timeout=10)
            status_res.raise_for_status()
            task_info = status_res.json()
            status = task_info["status"]
            
            if status == "success":
                print("\n\n🎉 音乐生成成功!")
                result = task_info.get("result", {})
                urls = result.get("song_url_list", [])
                
                print("\n🎵 音乐下载链接:")
                for i, url in enumerate(urls, 1):
                    print(f"   [{i}] {url}")
                
                if not urls and result.get("song_url"):
                    print(f"   [1] {result['song_url']}")
                
                break
                
            elif status == "failed":
                print(f"\n\n❌ 任务执行失败: {task_info.get('error')}")
                break
                
            else:
                # 打印进度点
                elapsed = int(time.time() - start_time)
                print(f"\r   状态: {status} (已耗时 {elapsed}s)...", end="", flush=True)
                
        except Exception as e:
            print(f"\n⚠️ 查询状态时出错: {e}")
            
        time.sleep(5)  # 每 5 秒轮询一次

if __name__ == "__main__":
    test_prompt = "A chill lofi beat for coding with rainy window background"
    if len(sys.argv) > 1:
        test_prompt = " ".join(sys.argv[1:])
        
    test_generate_song(test_prompt)
