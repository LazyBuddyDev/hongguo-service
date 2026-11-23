# 红果服务维护指南

Windows x64 独立红果服务，负责账号、搜索、官方收藏、观看进度、封面与媒体准备。宿主通过 JSON Lines 调用，在 WebView 中解码和呈现媒体。

[实现入口](docs/README.md#实现入口) · [业务 API](docs/module-api.md) · [构建与打包](README.md)。源码、文档、开发方案和构建产物按[统一文件放置规范](https://github.com/LazyBuddyDev/LazyBuddy/blob/main/docs/file-layout.md)归位。

- 账号作用域、官方读回和进度合并遵循[业务 API](docs/module-api.md)。隔离验证使用独立凭据和数据目录，真实账号写入须单独授权。
- 媒体会话、候选下一集、取源与回环限制见[浏览器播放契约](docs/browser-playback.md)。GPU 纹理交接仅适用于[可选原生消费者](docs/media-runtime.md#消费者责任)。宿主交互遵循[宿主 UI 规范](https://github.com/LazyBuddyDev/LazyBuddy/blob/main/docs/ui-guidelines.md#媒体视图)。
- 默认功能包及私有 Python 运行时分别打包。原生解码运行时按需构建。保留私有工具链和 SDK，外部集成验证使用显式提供的宿主二进制和暂存包。
