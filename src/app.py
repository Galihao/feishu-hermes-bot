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
def process_with_agent(user_id, message_text, chat_type="private"):
    """
    处理用户消息并返回Agent回复
    这里接入你的Hermes Agent逻辑
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

**功能说明：**
• 支持多轮对话，我会记住上下文
• 支持群聊@我和私聊
• 可以帮你查资料、回答问题、协助工作

**提示：**
• 对话历史1小时后自动清除
• 如果回答不准确，可以尝试清除后重新提问"""
    
    # TODO: 在这里接入你的实际Agent逻辑
    # 示例：简单的 echo + 上下文
    
    # 构建提示（包含历史）
    context = ""
    if history:
        context = "\n".join([
            f"{'用户' if h['role'] == 'user' else '助手'}: {h['content']}"
            for h in history[-5:]  # 最近5条
        ])
    
    # 模拟Agent回复（你需要替换为实际的Agent调用）
    reply = simulate_agent_response(message_text, context, chat_type)
    
    # 保存到历史
    session_mgr.add_message(user_id, "user", message_text)
    session_mgr.add_message(user_id, "assistant", reply)
    
    return reply

def simulate_agent_response(message, context, chat_type):
    """
    模拟Agent回复 - 你需要替换为实际的Agent调用
    
    实际接入时，可以：
    1. 调用本地运行的Hermes Agent
    2. 调用远程API
    3. 使用其他AI服务
    """
    # 示例回复
    greetings = ["你好", "您好", "hello", "hi", "在吗"]
    
    msg_lower = message.lower().strip()
    
    if any(g in msg_lower for g in greetings):
        return """👋 你好！我是你的飞书Agent助手。

我可以帮你：
🔍 查询资料和信息
💡 解答问题
📝 协助文档编写
🤔 分析讨论

直接发送你的问题，我会尽力协助！如需查看帮助，发送 `/help`"""
    
    # 返回带上下文的回复示例
    if context:
        return f"📝 收到你的问题：\"{message}\"\n\n我会基于之前的对话上下文来回答。\n\n💡 **注意**：这是一个示例回复。你需要在代码中接入实际的Agent逻辑（见 `process_with_agent` 函数）。"
    else:
        return f"📝 收到你的问题：\"{message}\"\n\n💡 **注意**：这是一个示例回复。你需要在代码中接入实际的Agent逻辑（见 `process_with_agent` 函数）。"

# ============ Webhook处理 ============
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

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
