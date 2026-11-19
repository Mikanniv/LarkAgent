# 云雀（LarkAgent）

云雀是一个集成长期记忆、多模态情感陪伴、学业规划与溯源学习自习室的 AI 助手。后端负责对话编排、长期记忆、日记、情绪计算与学习资料库 RAG；`static/` 为 Web 端；`desktop/` 为本地 Electron 桌面壳与透明桌宠；`lark_app/` 为 Flutter 客户端。

## 环境安装与运行

推荐使用 Python 3.10（Conda / venv）：

```bash
conda create -n yunque python=3.10 -y
conda activate yunque
pip install -r requirements.txt
python app.py
```

端口、大模型 API、R2 与模型路径等配置由 `.env` 控制（参考 `.env.example`）。线上可通过 Cloudflare Tunnel 转发到本机 `127.0.0.1:8001`。

### 桌面端（透明桌宠）

```bash
cd desktop
npm install
npm start
```

macOS 也可直接双击 `desktop/启动云雀.command`。

## 目录结构

```text
agent/        大模型 API 调用、流式对话、附件解析、学习资料库 RAG 与学业辅导
cloudflare/   Worker 登录鉴权与 D1 账号库
core/         配置与通用工具
desktop/      Electron 本地桌面壳、透明桌宠与本地桥接
diary/        用户日记、AI 日记与 R2/本地存储
emotion/      多模态情绪识别与音视频特征处理
lark_app/     Flutter 客户端
memory/       ChromaDB 长期记忆与 v2 记忆管线
server/       HTTP / SSE 接口路由与业务编排
static/       Web 前端（Live2D 形象、聊天、自习室、资料库、日记、档案）
storage/      SQLite 持久化（对话、档案、自习室、学习资料库与切片关联）
```

## 核心功能

- **情感陪伴与长期记忆**：支持流式对话、多模态附件（图片/音频/文档）、交互式 HTML 卡片（`html-widget`）、长期记忆召回与 AI 日记。
- **开始学习！自习室与学习资料库**：
  - 全局学习资料库：支持上传 PDF / PPTX / DOCX / XLSX / CSV / Markdown / 代码 / 文本，按文件类型自动结构化切片，并为每个切片提取主题词元数据。
  - 按会话隔离关联：每个自习室会话自主勾选关联资料，严格仅检索与推荐已关联资料，避免干扰。
  - 溯源问答与防幻觉拒答：回答强制标注 `[Si]` 来源编号并可点击查看原切片；若最高相关度低于阈值则诚实拒答，并列出最相关的候选切片。
  - 继续学习推荐：基于已引用切片推荐下一个学习切片，附带主题词元数据，支持一键针对指定切片深入学习。
- **独立桌宠与 Live2D 形象**：支持主页坐姿形象视线跟随、独立桌面透明桌宠（鸟型 / Q 版小人切换）。

## 常用调试

```bash
# 查看长期记忆
python memory/visualize.py --k 20

# 导出记忆可视化 HTML
python memory/visualize.py --k 20 --html memories/memory_view.html

# 测试 R2 存储
python scripts/test_r2.py
```

## 仓库提交策略

`.env`、本地 `docs/` 文档、运行时 SQLite、Chroma 本地库、日记缓存、依赖目录与打包产物均不提交到仓库。
