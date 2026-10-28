# 云雀

云雀是一个多模态长期记忆情感陪伴 demo。后端负责情绪计算、长期记忆、日记和大模型回复；`static/` 是网页版；`lark_app/` 是 Android / Web 预览用的 Flutter 客户端。

## 运行后端

```bash
/opt/homebrew/Caskroom/miniforge/base/envs/ai/bin/python app.py
```

端口、通用大模型 API、R2、模型路径等配置由 `.env` 控制。线上通过 Cloudflare Tunnel 转发到 VM 本机 `127.0.0.1:8001`。

语音聊天使用 FunASR Paraformer 进行中文转写，并由 SELF-MM 音频分支计算情感得分。首次使用前需要安装 `requirements.txt` 中的 FunASR/ModelScope 依赖；默认使用 `paraformer-zh + fsmn-vad + ct-punc`，可通过 `FUNASR_MODEL`、`FUNASR_DEVICE` 配置。

## 目录

```text
agent/        大模型 API 调用、回复生成、记忆写入判断
cloudflare/   Worker 登录鉴权和 D1 账号库
core/         配置和通用工具
diary/        用户记、AI记、R2/本地日记存储
emotion/      SELF-MM 推理和文本/音频/视频特征处理
memory/       ChromaDB 长期记忆
server/       HTTP 接口编排
static/       Web demo
desktop/      本地桌面壳、透明桌宠和网页连接
storage/      SQLite 聊天记录、R2 工具
lark_app/     Flutter Android 客户端
docs/         架构文档、论文、软著材料
```

## 新版界面与桌宠

网页版以云雀的坐姿形象和气泡入口作为主页。进入聊天后，角色移到左侧，聊天框在右侧；左上角返回主页。坐姿人型已拆为独立图层并绑定头部 X/Y、瞳孔和眨眼参数；设置中可关闭视线跟随。气泡轻微起伏，支持减少动态效果的系统偏好。

可编辑 Cubism 工程、原生运行时模型、分层素材和制作记录见 [形象工程](art/live2d/human-v1/README.md)。网页使用独立的分层网格播放器，与导出的 Cubism 工程来自同一套关键形；未捆绑官方 Cubism Core。最新 v3 已统一两眼的基础素材与网格。v2 的官方 FREE 版打开与保存已由用户确认，v3 新眼型工程尚未另行人工复核。

独立桌宠需要启动本机桌面壳，支持鸟型 / Q版小人切换、拖动和右键隐藏。Mac 可双击 `desktop/启动云雀.command`，详细说明见 [桌面壳说明](desktop/README.md)。本版先提供界面与桌宠交互，后续再接入屏幕感知。

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
