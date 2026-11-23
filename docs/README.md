# 红果服务文档

- [账号、搜索、收藏、进度与封面API](module-api.md)
- [浏览器媒体资源、生命周期、网络与日志](browser-playback.md)
- [可选原生媒体运行时](media-runtime.md)
- [本地签名运行时](signer.md)
- [构建、打包与工具链](../README.md)
- [开发规范](../AGENTS.md)
- [统一文件放置规范](https://github.com/LazyBuddyDev/LazyBuddy/blob/main/docs/file-layout.md)

业务接口只在本仓库维护；宿主通用协议通过链接引用，交付和验证状态见[TASKS](../TASKS.md)。

## 实现入口

| 职责 | 入口 |
| --- | --- |
| 包入口、启动和方法派发 | [main.py](../main.py)、[__main__.py](../src/lazybuddy_hongguo/__main__.py)、[protocol.py](../src/lazybuddy_hongguo/protocol.py) |
| 账号、收藏、进度和凭据 | [account.py](../src/lazybuddy_hongguo/backend/account.py)、[credentials.py](../src/lazybuddy_hongguo/backend/credentials.py) |
| 浏览器媒体会话和输入 | [media.py](../src/lazybuddy_hongguo/media.py)、[app_input.py](../src/lazybuddy_hongguo/backend/app_input.py)、[progressive.py](../src/lazybuddy_hongguo/backend/progressive.py) |
| 封面与诊断 | [covers.py](../src/lazybuddy_hongguo/covers.py)、[diagnostics.py](../src/lazybuddy_hongguo/diagnostics.py) |
| Go 取源、Rust 搜索和可选原生媒体 | [main.go](../resolver/main.go)、[lib.rs](../search/src/lib.rs)、[lazybuddy_media.py](../runtimes/media/lazybuddy_media.py) |
| 定向验证和完整包 | [check-changes.py](../scripts/check-changes.py)、[package-modules.py](../scripts/package-modules.py)、[verify](../scripts/verify) |
