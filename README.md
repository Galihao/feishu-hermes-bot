# 飞书 Hermes Agent Bot

支持多轮对话的飞书机器人，可接入 Hermes Agent 为团队提供智能问答服务。

## 功能特性

- ✅ 支持私聊和群聊
- ✅ 多轮对话上下文记忆
- ✅ 会话过期自动清理（1小时）
- ✅ 内置帮助和清空对话命令
- ✅ 易于接入实际 Agent 逻辑

## 快速开始

### 1. 部署到 Render

#### 方法一：一键部署（推荐）

1. 先将代码推送到 GitHub
2. 登录 [Render](https://render.com)
3. 点击 "New +" → "Blueprint"
4. 选择你的 GitHub 仓库
5. Render 会自动读取 `render.yaml` 配置并部署

#### 方法二：手动创建

1. 登录 [Render](https://render.com)
2. 点击 "New +" → "Web Service"
3. 选择你的 GitHub 仓库
4. 配置：
   - **Name**: `feishu-hermes-bot`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn -w 2 -b 0.0.0.0:$PORT src.app:app`
   - **Environment Variables**:
     - `APP_ID`: `cli_a956dc22b7f81bc4`
     - `APP_SECRET`: `qBHtLBPtvkBUmSYXjMKIegpbPjgMcHY1`
5. 点击 "Create Web Service"

### 2. 配置飞书事件订阅

部署完成后，你会获得一个 URL：
```
https://feishu-hermes-bot-xxx.onrender.com
```

1. 打开 [飞书开放平台](https://open.feishu.cn/app/)
2. 进入你的应用 → "事件订阅"
3. 开启事件订阅，填写请求地址：
   ```
   https://feishu-hermes-bot-xxx.onrender.com/webhook/feishu
   ```
4. 添加订阅事件：`im.message.receive_v1`
5. 点击保存，验证通过即可

### 3. 发布应用

1. 在飞书开放平台 → "版本管理与发布"
2. 点击 "创建版本"
3. 填写版本信息，申请发布
4. 在飞书管理后台审批通过
5. 将机器人添加到群聊或私聊测试

## 使用说明

### 基础命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助信息 |
| `/clear` | 清空当前对话历史 |

### 交互方式

- **私聊**：直接发送消息给机器人
- **群聊**：@机器人后发送消息

## 接入实际 Agent

当前代码中的 `simulate_agent_response` 是模拟回复，你需要替换为实际的 Agent 调用。

### 修改位置

编辑 `src/app.py` 中的 `process_with_agent` 函数：

```python
def process_with_agent(user_id, message_text, chat_type="private"):
    # ... 命令处理代码 ...
    
    # 替换这部分为你的 Agent 调用
    reply = call_your_agent(user_id, message_text, history)
    
    # 保存到历史
    session_mgr.add_message(user_id, "user", message_text)
    session_mgr.add_message(user_id, "assistant", reply)
    
    return reply
```

### 接入方式示例

#### 方式一：本地 Hermes Agent

如果你的 Hermes Agent 运行在本地或其他服务器：

```python
def call_your_agent(user_id, message, history):
    import requests
    
    response = requests.post("http://your-agent-server:8080/chat", json={
        "user_id": user_id,
        "message": message,
        "history": history
    })
    return response.json()["reply"]
```

#### 方式二：OpenAI API

```python
def call_your_agent(user_id, message, history):
    import openai
    
    messages = [{"role": "system", "content": "You are a helpful assistant."}]
    for h in history:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": message})
    
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=messages
    )
    return response.choices[0].message.content
```

#### 方式三：自定义逻辑

```python
def call_your_agent(user_id, message, history):
    # 查资料、调数据库、调API等
    if "查订单" in message:
        return query_order(message)
    elif "报表" in message:
        return generate_report(message)
    else:
        return "我可以帮你查订单或生成报表，请告诉我具体需求。"
```

## 项目结构

```
feishu-hermes-bot/
├── src/
│   └── app.py          # 主应用代码
├── requirements.txt    # Python 依赖
├── Procfile            # Render 启动命令
├── render.yaml         # Render 部署配置
├── .gitignore
└── README.md           # 本文件
```

## 本地测试

```bash
# 安装依赖
pip install -r requirements.txt

# 设置环境变量
export APP_ID=cli_a956dc22b7f81bc4
export APP_SECRET=qBHtLBPtvkBUmSYXjMKIegpbPjgMcHY1

# 运行
python src/app.py

# 测试
open http://localhost:8080/health
```

## 注意事项

1. **会话存储**：当前使用内存存储会话，应用重启会丢失。生产环境建议改为 Redis。
2. **并发**：默认使用 2 个 gunicorn worker，可根据需要调整。
3. **日志**：可以通过 Render Dashboard 查看运行日志。
4. **休眠**：免费版 Render 服务 15 分钟无请求会休眠，首次请求可能需要 30 秒启动。

## 许可证

MIT
