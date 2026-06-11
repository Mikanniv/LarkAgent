# 云雀

云雀是一个多模态长期记忆情感陪伴 demo。后端负责情绪计算、长期记忆、日记和 Kimi 回复；`static/` 是网页版；`lark_app/` 是 Android / Web 预览用的 Flutter 客户端。

## 运行后端

```bash
/opt/homebrew/Caskroom/miniforge/base/envs/ai/bin/python app.py
```

端口、Kimi、R2、模型路径等配置由 `.env` 控制。线上通过 Cloudflare Tunnel 转发到 VM 本机 `127.0.0.1:8001`。

## 目录

```text
agent/        Kimi 调用、回复生成、记忆写入判断
cloudflare/   Worker 登录鉴权和 D1 账号库
core/         配置和通用工具
diary/        用户记、AI记、R2/本地日记存储
emotion/      SELF-MM 推理和文本/音频/视频特征处理
memory/       ChromaDB 长期记忆
server/       HTTP 接口编排
static/       Web demo
storage/      SQLite 聊天记录、R2 工具
lark_app/     Flutter Android 客户端
docs/         架构文档、论文、软著材料
```

## 常用调试

查看长期记忆：

```bash
/opt/homebrew/Caskroom/miniforge/base/envs/ai/bin/python memory/visualize.py --k 20
```

写入示例记忆并测试召回：

```bash
/opt/homebrew/Caskroom/miniforge/base/envs/ai/bin/python memory/visualize.py --seed-demo --user-id debug_user --query "我答辩很焦虑，希望你先安慰我" --k 3
```

导出记忆 HTML：

```bash
/opt/homebrew/Caskroom/miniforge/base/envs/ai/bin/python memory/visualize.py --k 20 --html memories/memory_view.html
```

测试 R2：

```bash
/opt/homebrew/Caskroom/miniforge/base/envs/ai/bin/python scripts/test_r2.py
```

## 数据策略

`.env`、运行时 SQLite、Chroma 本地库、日记缓存、安装依赖和构建产物不提交。模型权重、BERT、本地提取后的 `.pkl` 特征会保留在私有仓库中，方便两台设备同步。
