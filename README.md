# 云雀

云雀是一个本地运行的多模态情感陪伴 demo。当前后端使用 SELF_MM MediaPipe 版情感模型，并通过本地 BERT、LibROSA、MediaPipe 提取文本、音频、视觉特征。

## Run

```bash
/opt/homebrew/Caskroom/miniforge/base/envs/ai/bin/python app.py
```

默认服务地址由 `.env` 控制，当前示例端口为 `8001`。

## Project Layout

```text
core/          配置、路径、运行时工具
emotion/       SELF_MM 推理、媒体特征提取、情绪映射
agent/         Kimi 调用和回复策略
diary/         用户日记和 AI 记
server/        HTTP handler 和接口编排
emotion_model/ 训练与特征提取脚本
memory/        长期记忆库原型
static/        前端页面
data/          提取后的 pkl 特征
models/        本地模型权重和 BERT
memories/      本地运行时记忆数据
docs/          架构文档和参考材料
```

## Long-Term Memory Debug

长期记忆库使用 ChromaDB，运行时数据默认写入 `memories/chroma/`。调试时请使用已有的 `ai` 环境，不需要新建环境：

```bash
/opt/homebrew/Caskroom/miniforge/base/envs/ai/bin/python memory/test_memory.py
```

查看记忆库：

```bash
/opt/homebrew/Caskroom/miniforge/base/envs/ai/bin/python memory/visualize.py --k 20
```

写入示例记忆并按语义召回：

```bash
/opt/homebrew/Caskroom/miniforge/base/envs/ai/bin/python memory/visualize.py --seed-demo --user-id debug_user --query "我答辩很焦虑，希望你先安慰我" --k 3
```

导出 HTML 可视化页面：

```bash
/opt/homebrew/Caskroom/miniforge/base/envs/ai/bin/python memory/visualize.py --k 20 --html memories/memory_view.html
```

ChromaDB 的本地持久化库不适合多个调试脚本同时写入；调试时建议一个命令跑完后再跑下一个。

## Git Policy

This is currently a private two-device sync repo. Model weights and local BERT files are kept. Raw training data and raw media are ignored; extracted `.pkl` feature files are kept.
