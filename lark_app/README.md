# 云雀 Flutter App

云雀移动端 Flutter 项目。

## 本地 Web 调试代理

Flutter Web 在 localhost 里直连线上 Worker 时会遇到浏览器 CORS/Cookie 限制。可以先启动本地代理：

```bash
node scripts/dev_proxy.mjs
```

再启动 Flutter Web：

```bash
flutter run -d chrome --dart-define=YUNQUE_API_BASE=http://127.0.0.1:8787
```

Android/iOS 真机 App 不需要代理，默认直接请求：

```text
https://worker.lark.irises.me
```
