# 云雀项目上下文

本文档面向新的 Codex Session、Flutter 安卓端开发者和后续维护者。目标是让接手者快速理解云雀的整体架构、后端 API、数据流、记忆机制和论文方向。

## 1. 项目目标

云雀是一个“多模态长期记忆情感陪伴 Agent”。它不是单纯的聊天机器人，而是一个带情绪感知、长期记忆、日记复盘和用户反馈修正机制的陪伴系统。

核心目标包括：

- 通过文本、音频、视频估计用户当前情绪状态。
- 将情绪表示压缩为 `valence`、`arousal`、`label`、`confidence`，供回复模型和前端展示使用。
- 使用长期记忆让对话具有连续性，而不是每轮从零开始。
- 用“用户记 + AI记 + 用户 review”的闭环，让用户显式参与长期记忆修正。
- 优先做一个稳定、自然、可演示的系统，而不是端到端大模型训练系统。

当前系统路线是：

```text
文本主导 + 音频/视频情绪增强 + Kimi 回复 + Chroma 长期记忆 + AI记反馈修正
```

## 2. 整体架构

线上推荐架构：

```text
Flutter Android App / Web Demo
  |
  | HTTPS + Cookie
  v
Cloudflare Auth Worker
  |
  | X-Yunque-User-Id
  | X-Yunque-Internal-Secret
  v
Python Backend
  |
  |-- SELF-MM MediaPipe 情绪模型
  |-- Kimi k2.5 回复与记忆写入决策
  |-- ChromaDB 长期记忆
  |-- SQLite 聊天记录与 worker 状态
  |-- Local/R2 日记与 AI记
```

各层职责：

- Flutter/Web：采集文本、音频、视频；展示聊天、情绪、日历、AI记、长期记忆。
- Cloudflare Worker：注册、登录、会话 cookie、鉴权代理。
- Python 后端：情绪推理、回复生成、记忆召回、记忆写入、AI记生成与 review 写回。
- SQLite：轻量持久化聊天、待生成 AI记日期、每日衰减状态。
- ChromaDB：向量长期记忆库。
- R2/本地文件：用户日记、AI记 Markdown、AI记 JSON meta。

## 3. 代码结构

关键目录：

```text
app.py                         Python 后端入口
server/handlers.py             HTTP 路由
server/service.py              核心业务编排
core/config.py                 环境变量与路径
core/utils.py                  时间、工具函数
emotion/models.py              SELF-MM 模型封装
emotion/media.py               文本/音频/视频输入解析和特征提取
emotion/mapping.py             raw scores -> valence/arousal/label
agent/kimi.py                  Kimi API 调用
agent/replies.py               回复 prompt、记忆写入决策
memory/db.py                   ChromaDB client
memory/schema.py               长期记忆 schema、召回、衰减
diary/generator.py             结构化 AI记生成
diary/store.py                 用户记/AI记存储
storage/chat_store.py          SQLite 聊天和运行状态
storage/r2_store.py            Cloudflare R2 存储适配
static/                        Web Demo
cloudflare/lark-auth-worker/   Cloudflare 登录与代理 Worker
docs/                          架构文档、论文文档、参考文献
```

## 4. 后端启动与环境

当前本地 Python 环境路径：

```text
/opt/homebrew/Caskroom/miniforge/base/envs/ai
```

启动：

```bash
/opt/homebrew/Caskroom/miniforge/base/envs/ai/bin/python app.py
```

默认端口由 `.env` 或 `core/config.py` 决定：

```text
HOST=127.0.0.1
PORT=8001
```

关键环境变量：

```text
SELF_MM_MODEL_PATH=models/self_mm_mediapipe_best.pth
BERT_MODEL_PATH=models/bert-base-chinese
FACE_TASK_PATH=face_landmarker.task
MEMORY_DIR=memories
DIARY_DIR=memories/diaries
CHROMA_DIR=memories/chroma
CHAT_DB_PATH=memories/chat.sqlite3
KIMI_API / KIMI_API_KEY
KIMI_MODEL=kimi-k2.5
KIMI_API_BASE=https://api.moonshot.cn/v1
AI_DIARY_UPDATE_INTERVAL=180
DAILY_MEMORY_DECAY_THRESHOLD=0.05
R2_ENABLED=0/1
YUNQUE_INTERNAL_SECRET=<shared secret>
```

部署注意：

- SQLite、Chroma、日记目录会在 VM 上重新生成，不要提交数据文件。
- 若启用 Worker 代理，Python 后端应设置 `YUNQUE_INTERNAL_SECRET`，拒绝没有共享密钥的请求。
- 如果改了 `server/service.py` 或 `diary/generator.py`，需要重启 Python 后端和后台 worker。

## 5. 认证与路由

### 5.1 本地调试

本地直接请求 Python 后端：

```text
http://127.0.0.1:8001
```

如果请求头没有 `X-Yunque-User-Id`，后端默认使用：

```text
local_user
```

### 5.2 线上调用

线上建议 Flutter 调用 Worker：

```text
https://worker.lark.irises.me
```

Worker 负责：

- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`
- 代理其他 `/api/*` 到 Python 后端。

Worker 代理时会追加：

```text
X-Yunque-User-Id: <user id>
X-Yunque-Internal-Secret: <shared secret>
```

Python 后端只信任这两个头，不直接处理用户名密码。

Flutter 注意：

- 使用 Worker 时需要保存并发送 `yunque_session` cookie。
- Android 端可以用 `dio` + `cookie_jar` 或自己维护 cookie header。
- 如果直接调 Python 后端调试，可以手动加 `X-Yunque-User-Id: debug_user`。

## 6. 核心数据流

一次正常聊天：

```text
1. Flutter/Web 发送 POST /api/chat
2. 后端解析 message/text/speech_text
3. 后端解析可选 audio/video base64 或 path
4. LibROSA 提取音频 33 维特征
5. MediaPipe 提取视频 9 维特征
6. SELF-MM MediaPipe 模型输出 fusion/text/audio/video
7. emotion/mapping.py 计算 valence/arousal/label/confidence
8. Chroma 召回 top-3 长期记忆
9. Kimi k2.5 生成 1-3 句中文陪伴回复
10. Kimi/规则判断是否写入长期记忆
11. SQLite 保存用户消息和云雀回复
12. 当日日期写入 pending_ai_diary_dates
13. 返回情绪、回复、记忆、聊天记录、媒体特征
```

一次 AI记生成：

```text
1. ai_diary_worker 周期运行
2. 每轮先执行每日记忆衰减
3. 查询早于今天的 pending_ai_diary_dates
4. 从 SQLite 取对应日期聊天快照
5. 结合用户记生成结构化 AI记
6. 保存 <date>-ai.md 和 <date>-ai.json
7. 等待用户 review
```

一次 AI记 review：

```text
1. 用户确认/修正/删除/追加 AI记条目
2. POST /api/diary/review
3. 后端把条目映射为 event/routine/preference/relationship
4. 查找已有重复或同主题记忆
5. 按 confirm/correct/delete/append 更新或新建 Chroma 记忆
6. 更新 AI记 meta 中的 review_items 和 memory_links
```

## 7. 情绪模型与模态

模型：

```text
SELF_MM_MediaPipe: models/self_mm_mediapipe_best.pth
BERT: models/bert-base-chinese
```

输入模态：

- 文本：用户输入、ASR 文本或空字符串。
- 音频：音频文件或 base64，后端提取 33 维特征。
- 视频：视频文件或 base64，后端提取 9 维表情特征。

音频特征顺序：

```text
logF0
mfcc_01 ... mfcc_20
cqt_01 ... cqt_12
```

视频特征来自 `emotion_model/train_self_mm_mediapipe.py` 中 `VIDEO_FEATURE_ORDER`，当前 demo 规划是 9 维。

`emotion/mapping.py` 中的 valence 融合使用可用性掩码：

```text
valence = tanh((m_t*0.3*t + m_a*0.3*a + m_v*0.4*v) / (m_t*0.3 + m_a*0.3 + m_v*0.4))
```

若某模态不可用，其权重不参与分母。arousal 由文本/音频/视频强度和视频表情激活组合得到。

## 8. 长期记忆机制

长期记忆存储在 ChromaDB，默认路径：

```text
memories/chroma
```

记忆类型：

```text
event
routine
preference
relationship
summary
```

主召回只使用：

```text
event/routine/preference/relationship
```

`summary` 只保留归档，不作为聊天主召回内容。

记忆 metadata 主要字段：

```json
{
  "date": "2026-06-01",
  "timestamp": "2026-06-01T12:00:00+08:00",
  "user": "user",
  "user_id": "uuid-or-local_user",
  "type": "event",
  "source": "conversation",
  "has_emotion": true,
  "valence": -0.2,
  "arousal": 0.7,
  "confidence": 0.7,
  "importance": 0.66,
  "importance_0": 0.66,
  "confirmation": "none",
  "text": true,
  "audio": false,
  "video": false,
  "text_available": true,
  "audio_available": false,
  "video_available": false
}
```

初始重要度由类型、来源、置信度、确认状态决定：

- preference 基础值最高。
- diary_user 有正向加成。
- inference 有负向加成。
- confirmed/corrected 有确认加成。

召回公式：

```text
s = alpha * (1 - distance) + beta * importance + gamma * recency
alpha=0.60, beta=0.35, gamma=0.05
```

每日衰减：

```text
importance = importance_0 * exp(elapsed_days * (importance_0 - 1))
```

当衰减后 importance 低于阈值 `0.05`，`apply_decay` 会删除该记忆。每日是否已衰减记录在 SQLite `runtime_state.last_memory_decay_date`。

## 9. AI记机制

AI记是 v1.1 的核心创新点之一。它不是主召回记忆，而是一个可读、可确认、可修正的“理解草稿”。

AI记 schema：

```json
{
  "date": "2026-05-21",
  "version": "v1.1",
  "summary": {
    "overall_state": "",
    "emotion_label": "",
    "valence": 0.0,
    "arousal": 0.0,
    "fusion_score": 0.0
  },
  "content": {
    "events": [],
    "routines": [],
    "preferences": [],
    "relationships": []
  },
  "review": {
    "status": "pending",
    "items": [],
    "review_text": "",
    "review_timestamp": "",
    "memory_links": {
      "preferences": [],
      "events": [],
      "routines": [],
      "relationships": [],
      "summary": []
    }
  }
}
```

展示模板：

```text
AI记 YYYY-MM-DD
今天聊完之后，云雀想先把对你的理解记下来。如果哪里不对，你直接改我就好。

今天的整体感觉
云雀觉得...

云雀觉得今天比较重要的事
E1. ...

云雀观察到的状态模式
R1. ...

云雀现在记下来的你的偏好
P1. ...

云雀留意到的关系线索
L1. ...

如果云雀理解错了
“P1 不对，应改成……”
“E2 可以删掉”
“补充一条偏好：……”
```

review 操作：

- `confirm`：用户确认理解正确，提高 confidence 和 importance。
- `correct`：用 `after` 替换原 content，写入 corrected 状态。
- `delete`：不立即物理删除，降低 confidence 和 importance，让衰减机制自然清理。
- `append`：新增一条长期记忆。

写回规则：

- `events -> event`
- `routines -> routine`
- `preferences -> preference`
- `relationships -> relationship`
- 不写“用户修正了某天 AI记：...”这种不可召回脏记忆。

## 10. SQLite 数据库结构

SQLite 路径：

```text
memories/chat.sqlite3
```

这个文件不应该提交到 Git。VM 上启动后会自动生成。

### chat_messages

```sql
CREATE TABLE chat_messages (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL,
  emotion_label TEXT,
  valence REAL,
  arousal REAL
);
```

用途：

- 保存最近和历史聊天。
- 生成 AI记时按日期恢复当天对话。
- 给 `/api/chat/history` 返回聊天记录。

### pending_ai_diary_dates

```sql
CREATE TABLE pending_ai_diary_dates (
  user_id TEXT NOT NULL,
  date_key TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, date_key)
);
```

用途：

- 标记哪些日期需要在过零点后生成 AI记。

### runtime_state

```sql
CREATE TABLE runtime_state (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

用途：

- 保存 `last_memory_decay_date`，避免同一天重复执行长期记忆衰减。

## 11. D1 认证数据库结构

Cloudflare Worker 使用 D1：

```sql
CREATE TABLE users (
  id TEXT PRIMARY KEY,
  username TEXT NOT NULL,
  username_key TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE sessions (
  token_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id)
);
```

Flutter 端无需直接访问 D1，只调用 Worker auth API。

## 12. API 说明

以下 API 在线上推荐通过 Worker 调用，路径基址为：

```text
https://worker.lark.irises.me
```

本地调试基址：

```text
http://127.0.0.1:8001
```

### 12.1 注册

```http
POST /api/auth/register
Content-Type: application/json
```

请求：

```json
{
  "username": "irises",
  "password": "至少8位"
}
```

响应：

```json
{
  "ok": true,
  "user": {
    "id": "uuid",
    "username": "irises"
  }
}
```

Worker 会设置 `yunque_session` cookie。

### 12.2 登录

```http
POST /api/auth/login
```

请求同注册。错误值包括：

```text
invalid_username
invalid_password
username_taken
invalid_credentials
```

### 12.3 当前用户

```http
GET /api/auth/me
```

响应：

```json
{
  "ok": true,
  "user": {
    "id": "uuid",
    "username": "irises"
  }
}
```

未登录时：

```json
{
  "ok": true,
  "user": null
}
```

### 12.4 聊天

```http
POST /api/chat
Content-Type: application/json
```

最小请求：

```json
{
  "message": "我今天有点焦虑",
  "timestamp": "2026-06-01T12:00:00+08:00"
}
```

带音视频请求：

```json
{
  "message": "我今天有点焦虑",
  "timestamp": "2026-06-01T12:00:00+08:00",
  "audio_base64": "data:audio/wav;base64,...",
  "video_base64": "data:video/webm;base64,..."
}
```

兼容字段：

```text
message/text
speech_text/speechText/transcript/asr_text
audio_path/audioPath/audio.data/audio.base64/audio_base64
video_path/videoPath/video.data/video.base64/video_base64
media.audio/media.video
proactive
proactive_reason/proactiveReason
```

重要响应字段：

```json
{
  "scores": {
    "fusion": 0.1,
    "text": 0.2,
    "audio": 0.0,
    "video": 0.0
  },
  "emotion": {
    "label": "中性",
    "valence": 0.1,
    "arousal": 0.4,
    "confidence": 0.6
  },
  "emotion_state": {
    "recent_va": [],
    "smoothed_va": {},
    "delta": 0.0,
    "significant_change": false,
    "threshold": 0.45
  },
  "agent": {
    "reply": "我在，慢慢说。",
    "source": "kimi",
    "error": ""
  },
  "memory": {},
  "long_memory": {
    "user_id": "uuid",
    "recalled": [],
    "update": {}
  },
  "modal_inputs": {},
  "media_features": {
    "audio": {},
    "video": {}
  },
  "chat_history": [],
  "timestamp": "2026-06-01T12:00:00+08:00"
}
```

Flutter 通常使用：

- `agent.reply` 展示气泡。
- `emotion` 展示主情绪、valence、arousal。
- `emotion_state.significant_change` 可用于触发主动回应逻辑。
- `chat_history` 用于页面恢复。
- `memory.selected` 可刷新日记区域。

### 12.5 只分析情绪

```http
POST /api/analyze
```

请求格式与 `/api/chat` 相同，但 `should_reply=false`，不会生成回复，也不会写聊天记录。适合移动端只想刷新情绪面板时使用。

### 12.6 聊天历史

```http
GET /api/chat/history?limit=20
```

响应：

```json
{
  "ok": true,
  "user_id": "uuid",
  "limit": 20,
  "items": [
    {
      "id": "...",
      "role": "user",
      "content": "...",
      "created_at": "...",
      "emotion_label": "低落",
      "valence": -0.3,
      "arousal": 0.5
    }
  ]
}
```

### 12.7 读取日记

```http
GET /api/diary?date=2026-06-01
```

响应：

```json
{
  "dates": ["2026-06-01"],
  "selected_date": "2026-06-01",
  "selected": {
    "date": "2026-06-01",
    "user_id": "uuid",
    "is_today": true,
    "user_markdown": "",
    "ai_markdown": "云雀正在努力总结中...",
    "ai_status": "not_ready",
    "ai_structured": null,
    "memory_links": {},
    "review_items": [],
    "ai_review_available": false,
    "ai_placeholder": "云雀正在努力总结中..."
  }
}
```

`ai_status` 可能值：

```text
not_ready
pending
confirmed
corrected
```

### 12.8 保存用户日记

```http
POST /api/diary/user
```

请求：

```json
{
  "date": "2026-06-01",
  "markdown": "今天我..."
}
```

响应同 `/api/diary`。

### 12.9 手动刷新 AI记

```http
POST /api/diary/refresh
```

请求：

```json
{
  "date": "2026-05-31"
}
```

注意：当前逻辑不会为今天生成 AI记，只处理早于今天的日期。

### 12.10 AI记 review

简单确认整篇 AI记：

```http
POST /api/diary/review
```

```json
{
  "date": "2026-05-31",
  "action": "confirm"
}
```

修正单条或补充：

```json
{
  "date": "2026-05-31",
  "action": "correct",
  "type": "event",
  "id": "E1",
  "correction": "用户已经成功保研。"
}
```

更精细的 items 模式：

```json
{
  "date": "2026-05-31",
  "action": "correct",
  "items": [
    {
      "type": "event",
      "id": "E1",
      "action": "correct",
      "before": "用户近期正在准备保研。",
      "after": "用户已经成功保研。"
    },
    {
      "type": "preference",
      "id": "P1",
      "action": "confirm",
      "before": "用户压力大时希望先被安慰。",
      "after": "用户压力大时希望先被安慰。"
    }
  ]
}
```

响应会包含：

```json
{
  "ok": true,
  "action": "correct",
  "memory": {
    "links": {
      "events": ["memory-id"],
      "preferences": [],
      "routines": [],
      "relationships": [],
      "summary": []
    },
    "items": []
  },
  "dates": [],
  "selected": {}
}
```

### 12.11 长期记忆查询

召回：

```http
GET /api/memory?query=保研&k=3
```

列出：

```http
GET /api/memory?k=20
```

按类型：

```http
GET /api/memory?query=老师&type=relationship&k=3
```

响应：

```json
{
  "mode": "recall",
  "query": "保研",
  "k": 3,
  "user_id": "uuid",
  "count": 10,
  "filtered_count": 8,
  "items": [
    {
      "id": "memory-id",
      "document": "用户已经成功保研。",
      "metadata": {},
      "distance": 0.2,
      "score": 0.8,
      "semantic_similarity": 0.8,
      "recency": 0.9
    }
  ]
}
```

### 12.12 删除和清理

删除单条：

```http
POST /api/memory/delete
```

```json
{
  "id": "memory-id"
}
```

清空某类或全部长期记忆：

```http
POST /api/memory/clear
```

```json
{
  "type": "event"
}
```

清空当前用户的记忆、日记、聊天：

```http
POST /api/user/clear
```

```json
{
  "include_local_user": true
}
```

手动执行记忆衰减：

```http
POST /api/memory/decay
```

```json
{
  "threshold": 0.05
}
```

## 13. Flutter 安卓端目标

建议新 Flutter App 的第一版目标：

1. 登录/注册页。
2. 聊天页：文本输入、云雀回复、历史记录恢复。
3. 情绪面板：展示 `label`、`valence`、`arousal`、`confidence`。
4. 日记页：日历、用户记编辑、AI记展示、确认/修改。
5. 记忆调试页：输入 query，查看 top-k 召回。
6. 设置页：后端地址、登出、清理本地缓存。

第一版移动端建议先不做：

- 手机端实时视频情绪识别。
- 本地 Chroma 或本地 SELF-MM。
- 复杂主动唤醒后台服务。

可行分阶段：

### 阶段 1：纯文本 Demo

- `/api/auth/*`
- `/api/chat`
- `/api/chat/history`
- `/api/diary`
- `/api/diary/user`
- `/api/diary/review`
- `/api/memory`

### 阶段 2：录音上传

- 使用 Flutter 录音插件生成 wav/m4a。
- 转 base64，传 `audio_base64`。
- 如果格式后端解码失败，优先转 wav。

### 阶段 3：短视频/表情上传

- 录制短视频或定帧视频。
- 转 base64，传 `video_base64`。
- 后端 MediaPipe 提取 9 维视频特征。

### 阶段 4：移动端体验优化

- 本地缓存最近 20 条聊天。
- Cookie 持久化。
- AI记 review 做成条目级交互。
- 情绪波动显著时显示轻提示，而不是频繁主动打扰。

## 14. Flutter API Client 建议

建议封装：

```text
YunqueApiClient
  - register(username, password)
  - login(username, password)
  - me()
  - chat(message, {audioBase64, videoBase64, proactive})
  - analyze(...)
  - chatHistory(limit)
  - getDiary(date)
  - saveUserDiary(date, markdown)
  - reviewDiary(date, action, ...)
  - queryMemory(query, k, type)
  - clearUserData()
```

状态模型建议：

```text
AuthState
ChatState
EmotionState
DiaryState
MemoryDebugState
```

移动端不要直接依赖 Web 的 `static/app.js` 逻辑，可以只参考它的页面状态和字段映射。

## 15. 当前开发进度

已完成：

- Python 后端可运行。
- SELF-MM MediaPipe 情绪模型接入。
- Kimi k2.5 对话模型接入。
- 长期记忆 ChromaDB 接入。
- 记忆写入决策与重复/合并逻辑。
- SQLite 聊天记录持久化。
- AI记 v1.1 结构化生成。
- AI记展示模板。
- AI记 review 写回长期记忆。
- 每日长期记忆衰减。
- Cloudflare Worker 登录和 API 代理。
- Web Demo：聊天、情绪、日记、记忆库可视化。

仍需完善：

- Flutter 安卓端项目尚未创建。
- 移动端 cookie/session 管理需要实现。
- 移动端音频/视频上传格式需要实测。
- AI记条目级 review 的移动端交互还未设计。
- 用户日记与长期记忆在多设备上的数据同步策略还需要继续打磨。
- 线上 Python 后端稳定性、systemd、日志和模型冷启动需要继续整理。

## 16. 当前论文方向

论文可以围绕“多模态情绪陪伴中的长期记忆校准机制”展开，而不是把重点放在训练一个全新的多模态模型。

建议主线：

```text
多模态情绪感知 + 长期记忆召回 + AI记反馈修正 + 用户可控记忆更新
```

可强调的创新点：

- AI记作为中间整理层，不直接作为主召回记忆。
- 用户 review 不是普通反馈文本，而是定向更新 `event/routine/preference/relationship` 长期记忆。
- 用 confirm/correct/delete/append 四类操作把用户反馈映射到长期记忆生命周期。
- 结合 `importance/confidence/recency/confirmation` 实现记忆召回与遗忘。
- 工程上支持真实对话、用户日记、长期记忆和多模态情绪的统一闭环。

可评估指标：

- 回复自然度或用户满意度。
- 记忆召回相关性。
- AI记条目准确率。
- Feedback Adoption Rate：被正确采纳的 review items / 全部 review items。
- 记忆污染率：错误、重复、低价值记忆比例。
- 消融实验：无记忆、仅自动记忆、AI记 + review。

参考文献线索：

- Russell, J. A. A Circumplex Model of Affect：valence/arousal 情绪空间基础。
- DialogueRNN：对话情绪识别中的上下文建模。
- MulT：多模态 Transformer 融合代表工作。
- SELF-MM：自监督多模态情感分析路线，支撑当前 SELF-MM 选择。
- openSMILE / eGeMAPS 相关工作：音频情绪特征工程参考。
- FACS / MediaPipe FaceLandmarker 相关资料：面部动作与视觉情绪线索参考。

本项目当前更适合定位为“系统设计 + 记忆机制创新 + 可运行 demo”，不是端到端训练新模型的论文。

## 17. 给新 Agent 的开发建议

如果你在新 Flutter 项目里接手：

1. 先读本文档和 `docs/AGENTS.md`。
2. 先实现 Worker auth，再实现 `/api/chat`。
3. 先只做文本聊天和历史记录，不要一开始硬接音视频。
4. 再接日记、AI记、记忆调试页。
5. 所有时间戳使用中国时间 ISO：`YYYY-MM-DDTHH:mm:ss+08:00`。
6. 不要在移动端复刻长期记忆算法，移动端只展示后端返回值。
7. 不要提交 SQLite、Chroma、R2 密钥、`.env`、模型缓存。
8. 如果发现文档和代码不一致，以代码为准，然后更新本文档。
