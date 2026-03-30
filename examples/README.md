# SunoSongsCreator API 示例

本项目提供了一系列 API 客户端示例，演示如何异步调用 Suno 歌曲生成接口并轮询获取结果。

## 准备工作

1.  **启动 API 服务**：
    在项目根目录下运行（默认开启 **8005** 端口）：
    ```bash
    uv run uvicorn api.main:app --port 8005
    ```
    
2.  **注册账号**：
    在使用生成功能前，你需要通过 API 注册至少一个有效的 Suno Cookie：
    ```bash
    # 使用 curl 示例
    curl -X POST http://127.0.0.1:8005/api/accounts \
         -H "Content-Type: application/json" \
         -d '{"account_name": "MyAccount", "cookie": "your_suno_cookie_here"}'
    ```

3.  **安装依赖**：
    示例脚本依赖 `httpx`：
    ```bash
    pip install httpx
    ```

## 运行示例

进入根目录并运行对应的示例脚本：

### 1. 通用测试脚本
```bash
python examples/test_api.py "写一首关于程序员在深夜修 Bug 的流行摇滚"
```

### 2. 统一示例 (Unified Mode)
一个脚本覆盖所有常用字段，适合直接修改 payload 进行测试。
```bash
python examples/unified_mode.py
```

## 功能说明
1.  **异步生成**：任务提交后立即返回任务 ID，不阻塞。
2.  **非阻塞轮询**：脚本会每隔 5 秒查询一次任务状态。
3.  **模型选择**：支持 `model` 参数切换 Suno 模型版本。
4.  **自动完成判定**：只有当所有音乐片段状态均为 `complete` 时才返回结果。
