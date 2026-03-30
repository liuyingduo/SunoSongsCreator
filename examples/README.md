# SunoSongsCreator API 示例

本项目提供了一个简单的 API 客户端示例，演示如何异步调用 Suno 歌曲生成接口并轮询获取结果。

## 准备工作

1.  **启动 API 服务**：
    在项目根目录下运行：
    ```bash
    uv run uvicorn api.main:app
    ```
    
2.  **注册账号**：
    在使用生成功能前，你需要通过 API 注册至少一个有效的 Suno Cookie：
    ```bash
    # 使用 curl 或 Postman 示例
    curl -X POST http://127.0.0.1:8000/api/accounts \
         -H "Content-Type: application/json" \
         -d '{"account_name": "MyAccount", "cookie": "your_suno_cookie_here"}'
    ```

3.  **安装依赖**：
    示例脚本依赖 `httpx`：
    ```bash
    pip install httpx
    ```

## 运行示例

进入 `examples` 目录并运行脚本：

```bash
python examples/test_api.py "写一首关于程序员在深夜修 Bug 的流行摇滚"
```

脚本将自动执行以下操作：
1.  提交歌曲生成请求。
2.  获取任务 ID。
3.  每隔 5 秒查询一次任务状态。
4.  当任务成功完成时，打印所有的 MP3 下载链接。
