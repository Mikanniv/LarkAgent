# 云雀

云雀是一个本地运行的多模态情感陪伴 demo。当前后端使用 SELF_MM MediaPipe 版情感模型，并通过本地 BERT、LibROSA、MediaPipe 提取文本、音频、视觉特征。

## Run

```powershell
python app.py
```

默认服务地址由 `.env` 控制，当前示例端口为 `8001`。

## Project Layout

```text
core/          配置、路径、运行时工具
emotion/       SELF_MM 推理、媒体特征提取、情绪映射
agent/         Ollama 调用和回复策略
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

## Git Policy

This is currently a private two-device sync repo. Model weights and local BERT files are kept. Raw training data and raw media are ignored; extracted `.pkl` feature files are kept.
