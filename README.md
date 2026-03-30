# SunoSongsCreator

High-quality songs generation by https://www.suno.ai/. Reverse engineered API.

## 项目结构

```
suno/           # Suno 逆向 API 代码（底层库）
api/             # FastAPI 服务层（对外 API）
```

## Suno 逆向库（CLI / SDK 用）

```bash
pip install -e .
suno --prompt 'a big red dream song'
```

```python
from suno import SongsGen

i = SongsGen("cookie")
print(i.get_limit_left())
i.save_songs("a blue cyber dream song", "./output")
```

## API 服务

### 启动

```bash
# 安装依赖
pip install -e .

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入 MONGODB_URL 和其他配置

# 启动服务
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

### API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/accounts` | 注册账号（发送 cookie） |
| GET | `/api/accounts` | 列出所有已注册账号 |
| DELETE | `/api/accounts/{email}` | 删除账号 |
| POST | `/api/tasks` | 创建歌曲生成任务 |
| GET | `/api/tasks/{task_id}` | 查询任务状态 |
| GET | `/api/health` | 健康检查 |

### API 示例

```bash
# 注册账号
curl -X POST "http://localhost:8000/api/accounts" \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "cookie": "__session=xxxx"}'

# 创建生成任务
curl -X POST "http://localhost:8000/api/tasks" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "a big red dream song"}'

# 查询任务
curl "http://localhost:8000/api/tasks/<task_id>"
```

## 配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `MONGODB_URL` | `mongodb://localhost:27017` | MongoDB 连接地址 |
| `MONGODB_DB` | `suno_api` | 数据库名 |
| `POOL_MAX_SIZE` | `10` | 账号池最大容量 |
| `API_HOST` | `0.0.0.0` | 服务监听地址 |
| `API_PORT` | `8000` | 服务监听端口 |
| `SCHEDULER_HOUR` | `0` | 每日调度时间（小时，0-23） |
| `SCHEDULER_MINUTE` | `0` | 每日调度时间（分钟） |

## 架构说明

- **账号池**：维护最多 N 个有余量的账号，自动调度生成请求
- **余额同步**：每次生成请求后自动更新余额；每天凌晨自动刷新所有账号余额
- **异步化**：所有数据库操作、HTTP 请求、调度任务均为异步
