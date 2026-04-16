from flask import Flask, request, jsonify
import os
import json
import requests
import time
from datetime import datetime
from collections import defaultdict
import threading

app = Flask(__name__)

# ============ 配置 ============
APP_ID = os.environ.get("APP_ID", "cli_a956dc22b7f81bc4")
APP_SECRET = os.environ.get("APP_SECRET", "qBHtLBPtvkBUmSYXjMKIegpbPjgMcHY1")
KIMI_API_KEY = os.environ.get("KIMI_API_KEY", "sk-NPfvTI4bxNN0tEwdqyFwpron9qwugQHgwZTGKbP5HoW0bfcO")

# ============ 会话存储（多轮对话）===========
class SessionManager:
    def __init__(self, max_history=10, ttl=3600):
        self.sessions = defaultdict(list)
        self.last_activity = {}
        self.max_history = max_history
        self.ttl = ttl  # 会话过期时间（秒）
        self.lock = threading.Lock()
    
    def get_history(self, user_id):
        """获取用户对话历史"""
        with self.lock:
            self._cleanup_expired()
            return self.sessions.get(user_id, [])
    
    def add_message(self, user_id, role, content):
        """添加消息到历史记录"""
        with self.lock:
            self.sessions[user_id].append({
                "role": role,
                "content": content,
                "timestamp": datetime.now().isoformat()
            })
            # 只保留最近N条
            if len(self.sessions[user_id]) > self.max_history:
                self.sessions[user_id] = self.sessions[user_id][-self.max_history:]
            self.last_activity[user_id] = time.time()
    
    def clear(self, user_id):
        """清空会话"""
        with self.lock:
            if user_id in self.sessions:
                del self.sessions[user_id]
            if user_id in self.last_activity:
                del self.last_activity[user_id]
    
    def _cleanup_expired(self):
        """清理过期会话"""
        now = time.time()
        expired = [
            user_id for user_id, last_time in self.last_activity.items()
            if now - last_time > self.ttl
        ]
        for user_id in expired:
            if user_id in self.sessions:
                del self.sessions[user_id]
            del self.last_activity[user_id]

session_mgr = SessionManager(max_history=10, ttl=3600)

# ============ 飞书API工具 ============
class FeishuAPI:
    def __init__(self):
        self.token = None
        self.token_expire = 0
    
    def get_tenant_access_token(self):
        """获取租户访问令牌"""
        if self.token and time.time() < self.token_expire - 300:
            return self.token
        
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        resp = requests.post(url, json={
            "app_id": APP_ID,
            "app_secret": APP_SECRET
        })
        data = resp.json()
        
        if data.get("code") == 0:
            self.token = data["tenant_access_token"]
            self.token_expire = time.time() + data["expire"]
            return self.token
        else:
            raise Exception(f"获取token失败: {data}")
    
    def send_message(self, receive_id, content, msg_type="text", receive_id_type="open_id"):
        """发送消息"""
        token = self.get_tenant_access_token()
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        headers = {"Authorization": f"Bearer {token}"}
        
        if msg_type == "text":
            payload = {
                "receive_id": receive_id,
                "msg_type": "text",
                "content": json.dumps({"text": content})
            }
        elif msg_type == "interactive":
            payload = {
                "receive_id": receive_id,
                "msg_type": "interactive",
                "content": json.dumps(content)
            }
        else:
            payload = {
                "receive_id": receive_id,
                "msg_type": msg_type,
                "content": content
            }
        
        resp = requests.post(
            url, 
            headers=headers, 
            params={"receive_id_type": receive_id_type},
            json=payload
        )
        return resp.json()

feishu_api = FeishuAPI()

# ============ Agent处理逻辑 ============
def call_kimi_api(messages):
    """调用Kimi API获取回复"""
    try:
        url = "https://api.moonshot.cn/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {KIMI_API_KEY}"
        }
        payload = {
            "model": "moonshot-v1-8k",  # 修正模型名称
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 2000
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        data = response.json()
        
        print(f"[Kimi API] Status: {response.status_code}, Response: {data}")
        
        if response.status_code == 200 and "choices" in data:
            return data["choices"][0]["message"]["content"]
        else:
            error_msg = data.get("error", {}).get("message", str(data))
            print(f"[Kimi API 错误] {error_msg}")
            return f"😢 调用AI服务出错: {error_msg}"
    except Exception as e:
        print(f"调用Kimi API失败: {e}")
        return "😢 服务暂时不可用，请稍后重试"

def process_with_agent(user_id, message_text, chat_type="private"):
    """
    处理用户消息并返回Agent回复
    接入 Kimi API
    """
    # 获取对话历史
    history = session_mgr.get_history(user_id)
    
    # 特殊命令处理
    if message_text.strip() in ["/clear", "/重置", "清除对话"]:
        session_mgr.clear(user_id)
        return "✅ 对话历史已清除，我们可以开始新的对话了~"
    
    if message_text.strip() in ["/help", "/帮助"]:
        return """🤖 **飞书Agent助手使用说明**

**可用命令：**
• `/help` 或 `/帮助` - 显示此帮助
• `/clear` 或 `/重置` - 清除对话历史，重新开始
• `/github` 或 `热门项目` - 查看今日GitHub热门
• `/builderpulse` 或 `/日报` - 查看今日市场洞察报告

**功能说明：**
• 支持多轮对话，AI会记住上下文
• 支持群聊@我和私聊
• 基于 Kimi AI 模型（moonshot-v1-8k）
• 每日早晨9点自动推送GitHub热门项目
• 每日早晨9点自动推送BuilderPulse市场报告

**提示：**
• 对话历史1小时后自动清除
• 如果回答不准确，可以尝试清除后重新提问"""
    
    # 构建消息历史
    messages = [{"role": "system", "content": "你是一个有用的AI助手，在飞书平台为用户提供帮助。请用简洁、专业的方式回答问题。"}]
    
    # 添加历史对话
    for h in history[-5:]:  # 最近5条
        role = "user" if h["role"] == "user" else "assistant"
        messages.append({"role": role, "content": h["content"]})
    
    # 添加当前消息
    messages.append({"role": "user", "content": message_text})
    
    # 调用Kimi API
    reply = call_kimi_api(messages)
    
    # 保存到历史
    session_mgr.add_message(user_id, "user", message_text)
    session_mgr.add_message(user_id, "assistant", reply)
    
    return reply

# ============ 每日GitHub热门项目推送 ============
TARGET_USER_ID = os.environ.get("TARGET_USER_ID", "")  # 设置接收推送的用户ID

def get_github_trending():
    """获取GitHub最近7天最热门的10个项目"""
    try:
        # 计算7天前的日期
        from datetime import datetime, timedelta
        seven_days_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        
        # GitHub Search API: 最近7天创建的、star最多的项目
        url = "https://api.github.com/search/repositories"
        params = {
            "q": f"created:>{seven_days_ago}",
            "sort": "stars",
            "order": "desc",
            "per_page": 10
        }
        headers = {"Accept": "application/vnd.github.v3+json"}
        
        response = requests.get(url, params=params, headers=headers, timeout=30)
        data = response.json()
        
        if response.status_code == 200 and "items" in data:
            return data["items"]
        else:
            print(f"GitHub API错误: {data}")
            return []
    except Exception as e:
        print(f"获取GitHub项目失败: {e}")
        return []
    
    if event_type == "im.message.receive_v1":
        event = data.get("event", {})
        message = event.get("message", {})
        sender = event.get("sender", {})
        
        # 获取消息信息
        msg_type = message.get("message_type")
        chat_type = message.get("chat_type")  # private / group
        chat_id = message.get("chat_id")
        user_id = sender.get("sender_id", {}).get("open_id")
        user_name = sender.get("sender_id", {}).get("user_id", "未知用户")
        
        # 解析消息内容
        content = json.loads(message.get("content", "{}"))
        
        if msg_type == "text":
            text = content.get("text", "").strip()
            
            # 群聊中只处理@机器人的消息
            if chat_type == "group":
                # 获取被@的用户列表
                mentions = message.get("mentions", [])
                # 检查是否被@
                is_mentioned = any(
                    m.get("name", "") in text or m.get("key", "") in text
                    for m in mentions
                )
                
                # 如果没有被@且不是命令，忽略消息
                if not is_mentioned and not text.startswith("/"):
                    return jsonify({"status": "ignored"})
                
                # 移除@机器人的文本
                for mention in mentions:
                    text = text.replace(f"@{mention.get('name', '')}", "").strip()
            
            print(f"[{chat_type}] {user_name}: {text}")
            
            # 处理消息
            reply = process_with_agent(user_id, text, chat_type)
            
            # 发送回复
            if chat_type == "group":
                # 群聊回复到群里
                feishu_api.send_message(chat_id, reply, receive_id_type="chat_id")
            else:
                # 私聊回复给用户
                feishu_api.send_message(user_id, reply)
        
        return jsonify({"status": "ok"})
    
    return jsonify({"status": "ignored"})

@app.route('/health', methods=['GET'])
def health_check():
    """健康检查"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "active_sessions": len(session_mgr.sessions)
    })

@app.route('/get-user-id', methods=['GET', 'POST'])
def get_user_id():
    """获取当前用户ID（调试用）"""
    data = request.json or {}
    user_id = data.get("user_id", "")
    return jsonify({
        "your_user_id": user_id,
        "tip": "在飞书发消息后，查看Render日志找到 [private] ou_xxxxx 格式的ID"
    })

@app.route('/', methods=['GET'])
def index():
    """首页"""
    return jsonify({
        "name": "飞书Hermes Agent Bot",
        "version": "1.0.0",
        "endpoints": {
            "webhook": "/webhook/feishu",
            "health": "/health"
        }
    })

# ============ 每日GitHub热门项目推送 ============
TARGET_USER_ID = os.environ.get("TARGET_USER_ID", "")  # 设置接收推送的用户ID

def get_github_trending():
    """获取GitHub最近7天最热门的10个项目"""
    try:
        # 计算7天前的日期
        from datetime import datetime, timedelta
        seven_days_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        
        # GitHub Search API: 最近7天创建的、star最多的项目
        url = "https://api.github.com/search/repositories"
        params = {
            "q": f"created:>{seven_days_ago}",
            "sort": "stars",
            "order": "desc",
            "per_page": 10
        }
        headers = {"Accept": "application/vnd.github.v3+json"}
        
        response = requests.get(url, params=params, headers=headers, timeout=30)
        data = response.json()
        
        if response.status_code == 200 and "items" in data:
            return data["items"]
        else:
            print(f"GitHub API错误: {data}")
            return []
    except Exception as e:
        print(f"获取GitHub项目失败: {e}")
        return []

def format_repo_info(repo):
    """格式化单个项目信息"""
    name = repo.get("full_name", "")
    description = repo.get("description") or "暂无描述"
    stars = repo.get("stargazers_count", 0)
    language = repo.get("language") or "未知"
    url = repo.get("html_url", "")
    
    return f"""**{name}** ⭐ {stars}
📝 {description}
🔤 语言: {language}
🔗 {url}
"""

def generate_daily_report():
    """生成每日项目报告"""
    repos = get_github_trending()
    
    if not repos:
        return "❌ 获取GitHub热门项目失败，请稍后重试"
    
    today = datetime.now().strftime("%Y年%m月%d日")
    
    message = f"""🌅 **GitHub每日热门项目** ({today})

以下是过去7天内最受欢迎的 **10个开源项目**：

"""
    
    for i, repo in enumerate(repos, 1):
        message += f"\n{i}. {format_repo_info(repo)}\n"
    
    message += """
💡 **提示**
• 发送 `/github` 可随时查看最新热门项目
• 每日早晨9点自动推送
• 数据来源: GitHub Search API
"""
    
    return message

@app.route('/cron/daily-github', methods=['POST', 'GET'])
def cron_daily_github():
    """定时任务：每日推送GitHub热门项目"""
    print(f"[{datetime.now()}] 执行每日GitHub推送任务")
    
    if not TARGET_USER_ID:
        print("错误: 未设置 TARGET_USER_ID 环境变量")
        return jsonify({"status": "error", "message": "TARGET_USER_ID not set"}), 400
    
    try:
        # 生成报告
        report = generate_daily_report()
        
        # 发送给目标用户
        result = feishu_api.send_message(TARGET_USER_ID, report)
        
        if result.get("code") == 0:
            print(f"成功推送GitHub日报给用户: {TARGET_USER_ID}")
            return jsonify({"status": "success", "message": "Daily report sent"})
        else:
            print(f"推送失败: {result}")
            return jsonify({"status": "error", "message": result}), 500
            
    except Exception as e:
        print(f"执行定时任务出错: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ============ BuilderPulse 每日报告推送 ============
def get_builderpulse_report():
    """获取BuilderPulse最新每日报告"""
    try:
        # 获取今天的日期
        today = datetime.now().strftime("%Y-%m-%d")
        year = datetime.now().strftime("%Y")
        
        # BuilderPulse GitHub 原始文件地址
        url = f"https://raw.githubusercontent.com/BuilderPulse/BuilderPulse/main/zh/{year}/{today}.md"
        
        response = requests.get(url, timeout=30)
        
        if response.status_code == 200:
            return response.text
        else:
            # 如果今天的还没有，尝试获取昨天的
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            url = f"https://raw.githubusercontent.com/BuilderPulse/BuilderPulse/main/zh/{year}/{yesterday}.md"
            response = requests.get(url, timeout=30)
            
            if response.status_code == 200:
                return response.text
            else:
                return None
    except Exception as e:
        print(f"获取BuilderPulse报告失败: {e}")
        return None

def format_builderpulse_report(markdown_content):
    """格式化BuilderPulse报告为飞书消息"""
    if not markdown_content:
        return "❌ 暂无报告，请稍后重试"
    
    # 提取标题和主要内容
    lines = markdown_content.split('\n')
    
    # 查找今日标题和核心建议
    title = ""
    insight = ""
    reading_link = ""
    
    for i, line in enumerate(lines):
        if line.startswith('# ') and not title:
            title = line.replace('# ', '').strip()
        elif line.startswith('💡') and not insight:
            insight = line.strip()
        elif '阅读今日报告' in line or '完整报告' in line:
            # 提取链接
            if 'github.com' in line:
                reading_link = line.split('(')[1].split(')')[0] if '(' in line else ""
    
    today = datetime.now().strftime("%Y年%m月%d日")
    
    # 构建消息
    message = f"""📋 **BuilderPulse 每日报告** ({today})

**{title}**

{insight}

"""
    
    # 添加关键要点（提取前5个要点）
    message += "📌 **今日要点**:\n"
    count = 0
    for line in lines:
        if line.strip().startswith('- ') or line.strip().startswith('* '):
            message += f"• {line.strip()[2:]}\n"
            count += 1
            if count >= 5:
                break
    
    message += f"""
📖 **阅读完整报告**:
https://github.com/BuilderPulse/BuilderPulse

⭐ **功能**
• 每日9点自动推送市场洞察
• 发送 `/builderpulse` 或 `/日报` 随时查看
• 数据来源: Hacker News, GitHub, Product Hunt, Reddit等
"""
    
    return message

def generate_builderpulse_daily():
    """生成BuilderPulse每日报告"""
    content = get_builderpulse_report()
    return format_builderpulse_report(content)

@app.route('/cron/daily-builderpulse', methods=['POST', 'GET'])
def cron_daily_builderpulse():
    """定时任务：每日推送BuilderPulse报告"""
    print(f"[{datetime.now()}] 执行每日BuilderPulse推送任务")
    
    if not TARGET_USER_ID:
        print("错误: 未设置 TARGET_USER_ID 环境变量")
        return jsonify({"status": "error", "message": "TARGET_USER_ID not set"}), 400
    
    try:
        # 生成报告
        report = generate_builderpulse_daily()
        
        # 发送给目标用户
        result = feishu_api.send_message(TARGET_USER_ID, report)
        
        if result.get("code") == 0:
            print(f"成功推送BuilderPulse日报给用户: {TARGET_USER_ID}")
            return jsonify({"status": "success", "message": "BuilderPulse report sent"})
        else:
            print(f"推送失败: {result}")
            return jsonify({"status": "error", "message": result}), 500
            
    except Exception as e:
        print(f"执行定时任务出错: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ============ 飞书Webhook处理 ============
@app.route('/webhook/feishu', methods=['POST'])
def feishu_webhook():
    """处理飞书事件回调"""
    data = request.json
    
    # 1. URL验证（首次配置时需要）
    if data.get("type") == "url_verification":
        challenge = data.get("challenge")
        print(f"[URL验证] challenge: {challenge}")
        return jsonify({"challenge": challenge})
    
    # 2. 处理事件
    header = data.get("header", {})
    event_type = header.get("event_type")
    
    if event_type == "im.message.receive_v1":
        event = data.get("event", {})
        message = event.get("message", {})
        sender = event.get("sender", {})
        
        # 获取消息信息
        msg_type = message.get("message_type")
        chat_type = message.get("chat_type")  # private / group
        chat_id = message.get("chat_id")
        user_id = sender.get("sender_id", {}).get("open_id")
        user_name = sender.get("sender_id", {}).get("user_id", "未知用户")
        
        # 解析消息内容
        content = json.loads(message.get("content", "{}"))
        
        if msg_type == "text":
            text = content.get("text", "").strip()
            
            # 群聊中只处理@机器人的消息
            if chat_type == "group":
                # 获取被@的用户列表
                mentions = message.get("mentions", [])
                # 检查是否被@
                is_mentioned = any(
                    m.get("name", "") in text or m.get("key", "") in text
                    for m in mentions
                )
                
                # 如果没有被@且不是命令，忽略消息
                if not is_mentioned and not text.startswith("/"):
                    return jsonify({"status": "ignored"})
                
                # 移除@机器人的文本
                for mention in mentions:
                    text = text.replace(f"@{mention.get('name', '')}", "").strip()
            
            print(f"[DEBUG] user_id={user_id}, chat_type={chat_type}, text={text}")
            
            # 处理手动触发GitHub日报命令
            if text.strip() in ["/github", "/今日热门", "热门项目"]:
                report = generate_daily_report()
                if chat_type == "group":
                    feishu_api.send_message(chat_id, report, receive_id_type="chat_id")
                else:
                    feishu_api.send_message(user_id, report)
                return jsonify({"status": "ok"})
            
            # 处理手动触发BuilderPulse日报命令
            if text.strip() in ["/builderpulse", "/日报", "市场报告", "洞察报告"]:
                report = generate_builderpulse_daily()
                if chat_type == "group":
                    feishu_api.send_message(chat_id, report, receive_id_type="chat_id")
                else:
                    feishu_api.send_message(user_id, report)
                return jsonify({"status": "ok"})
            
            # 处理消息
            reply = process_with_agent(user_id, text, chat_type)
            
            # 发送回复
            if chat_type == "group":
                # 群聊回复到群里
                feishu_api.send_message(chat_id, reply, receive_id_type="chat_id")
            else:
                # 私聊回复给用户
                feishu_api.send_message(user_id, reply)
        
        return jsonify({"status": "ok"})
    
    return jsonify({"status": "ignored"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
