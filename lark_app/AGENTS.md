# 云雀 Agent 快速指南

本文件给新的 Codex Session / Agent 使用，目标是在 5 分钟内接手云雀项目，尤其是后续 Flutter 安卓端开发。

## 项目目标

云雀是一个多模态情感陪伴 Agent。系统采集用户文本、音频、视频，预测情绪 `valence/arousal`，结合长期记忆生成自然中文陪伴回复，并通过“用户记 + AI记 + 用户 review”持续修正长期记忆。

## 当前代码入口

- Python 后端入口：`app.py`
- HTTP 路由：`server/handlers.py`
- 主业务逻辑：`server/service.py`
- 情绪模型：`emotion/models.py`、`emotion/mapping.py`、`emotion/media.py`
- 回复与写记忆决策：`agent/replies.py`、`agent/kimi.py`
- 长期记忆：`memory/schema.py`、`memory/db.py`
- AI记：`diary/generator.py`、`diary/store.py`
- SQLite 聊天/运行状态：`storage/chat_store.py`
- Cloudflare Auth Worker：`cloudflare/lark-auth-worker/`
- Web Demo：`static/`

## 架构一句话

Flutter/Web 客户端只负责采集和展示；Cloudflare Worker 负责登录、会话和代理；Python 后端负责情绪推理、Kimi 回复、记忆写入、AI记生成和 Chroma/SQLite/R2 数据操作。

## 线上调用路径

推荐移动端调用：

```text
Flutter App -> https://worker.lark.irises.me -> https://api.lark.irises.me
```

Worker 会在认证后转发：

```text
X-Yunque-User-Id: <user id>
X-Yunque-Internal-Secret: <shared secret>
```

本地调试可直接请求 Python 后端 `http://127.0.0.1:8001`，此时默认用户是 `local_user`。

## 核心 API

- `POST /api/auth/register`：Worker 注册，`{username,password}`。
- `POST /api/auth/login`：Worker 登录，返回 cookie session。
- `GET /api/auth/me`：Worker 获取当前用户。
- `POST /api/chat`：情绪分析 + 回复 + 记忆召回/写入。
- `POST /api/analyze`：只分析情绪，不生成回复。
- `GET /api/chat/history?limit=20`：读取 SQLite 聊天记录。
- `GET /api/diary?date=YYYY-MM-DD`：读取日历、用户记、AI记。
- `POST /api/diary/user`：保存用户日记。
- `POST /api/diary/refresh`：手动触发指定日期 AI记生成。
- `POST /api/diary/review`：确认、修正、删除、追加 AI记条目并写回长期记忆。
- `GET /api/memory?query=...&k=3&type=event`：调试召回或列出记忆。
- `POST /api/memory/delete`、`POST /api/memory/clear`、`POST /api/user/clear`：调试/清理数据。

## `/api/chat` 请求要点

常用 JSON：

```json
{
  "message": "用户输入",
  "timestamp": "2026-06-01T12:00:00+08:00",
  "audio_base64": "可选 data url/base64",
  "video_base64": "可选 data url/base64",
  "proactive": false
}
```

也兼容 `text`、`speech_text`、`audio.data/base64`、`video.data/base64`、`media.audio/video`。

## 数据流

1. 客户端发送文本和可选音视频。
2. 后端提取文本，音频用 LibROSA 33 维，视频用 MediaPipe 9 维。
3. SELF-MM MediaPipe 模型输出 `fusion/text/audio/video`。
4. `emotion/mapping.py` 根据可用模态计算 `valence/arousal/confidence/label`。
5. 召回 Chroma 长期记忆 top-k=3。
6. Kimi `kimi-k2.5` 生成回复。
7. Kimi/规则判断是否写入长期记忆。
8. 聊天写入 SQLite，日期加入待生成 AI记队列。

## AI记机制

- AI记不是主召回记忆，而是用户可读、可确认、可修正的中间整理层。
- 每天过后，`ai_diary_worker` 根据 SQLite 当日聊天 + 用户记生成结构化 AI记。
- v1.1 AI记包含 `summary`、`content.events/routines/preferences/relationships`、`review`。
- 用户 review 支持 `confirm/correct/delete/append`。
- review 后写入/更新真正的长期记忆，不写“用户修正了某天 AI记”这种脏 summary。

## 长期记忆机制

- 存储：ChromaDB，默认目录 `memories/chroma`。
- 类型：`event/routine/preference/relationship/summary`。
- 主召回只看 `event/routine/preference/relationship`，不看 `summary`。
- 召回分数：`s=0.6*(1-distance)+0.35*importance+0.05*recency`。
- 每天由 worker 对 `importance` 做一次衰减，低于阈值默认 `0.05` 会删除。

## 数据库

- SQLite：`memories/chat.sqlite3`，自动生成，不要提交到 Git。
- SQLite 表：`chat_messages`、`pending_ai_diary_dates`、`runtime_state`。
- Worker D1 表：`users`、`sessions`。
- 日记：本地 `memories/diaries/<user_id>/` 或 Cloudflare R2。

## Flutter 移动端目标

- 做原生移动聊天体验：登录、聊天、情绪展示、日记/AI记、记忆库调试。
- 手机端优先采集文本；音视频可后续接入录音/短视频并以 base64 上传。
- 不在 Flutter 端跑 SELF-MM/Chroma/Kimi，全部调用后端 API。
- 需要 cookie/session 管理；若走 Worker，要保存并发送 `yunque_session` cookie。

## 当前进度

- Web Demo 已有聊天、情绪展示、日记日历、AI记 review、记忆库可视化。
- 后端已接 Kimi k2.5、SELF-MM MediaPipe、SQLite 聊天、Chroma 长期记忆、R2 日记。
- v1.1 已实现 AI记结构化展示、review 写回长期记忆、每日记忆衰减。
- 安卓端尚未开始，建议新建 Flutter 项目并按 `PROJECT_CONTEXT.md` 对接 API。

## 工作规则

- 不要提交 `memories/`、`*.sqlite3`、Chroma 数据、R2 密钥、`.env`。
- 如果改 Python 后端或 AI记 worker，部署后要重启 Python 服务。
- 如果只改 `static/`，只需要重新部署静态站点。
- 学术/论文建议必须给可靠来源，优先引用 `docs/references/` 中的文献。
