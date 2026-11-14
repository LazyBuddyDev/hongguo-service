# 浏览器播放资源

红果服务负责身份、目录、单集权限、清晰度选择和有界媒体准备，输出受控的压缩MP4资源；浏览器负责解复用、解码、音画同步与呈现。服务不逐帧向JavaScript传像素，不自动转码。默认功能包只依赖私有Python及包内辅助程序，不要求GStreamer。构建见[README](../README.md)，账号方法见[业务API](module-api.md)，交付状态见[TASKS](../TASKS.md)。

## 私有控制协议

沿用API v1 JSON Lines，只有明确用户操作及当前可见页面所需请求可运行：

| 方法 | 参数 | 结果 |
| --- | --- | --- |
| `playback.open` | 字符串`series`、整数`episode`、可选字符串`quality`、明确`origin` | 新会话代数与loading状态 |
| `playback.status` | 无 | 当前loading/prepared/error、目录与资源 |
| `playback.report_error` | 整数`session`、浏览器媒体错误`code`（1–4） | 记录所属会话错误 |
| `playback.suspend/resume` | 整数`session` | 停止/允许资源读取，加载中suspend取消准备 |
| `playback.checkpoint` | `session`、秒数`position/duration`、可选布尔`final` | 保存真实观看断点，final请求提交 |
| `playback.close` | 整数`session` | 释放资源与输入进程，收尾已有进度事务 |

准备完成时返回`prepared: true`、`resource: {url, mime: "video/mp4"}`、`session`、`suspended`，以及脱敏错误、进度、分集与清晰度字段。`available_qualities`是数字数组（如`[360,720,1080]`），请求`quality`使用带p字符串（如`"720p"`），客户端在边界转换，不把旧集档位照搬给新集。档位来自当前集实际兼容结果。

接受open不代表浏览器已解码。仅当前可见页面轮询准备状态；用`loadedmetadata`、实际尺寸、帧回调`mediaTime`、媒体error与真实EOS反馈播放。请求seek目标、滑块预览或服务声明时长不能代替已观看帧时间。

## 本地媒体资源

URL为127.0.0.1上的随机短期会话能力，不是上游签名地址，不能持久化、输出到公开状态或日志。只允许open明确传入的Origin、精确Host及固定路径。浏览器使用CORS模式，例如`<video crossorigin="anonymous">`。

支持GET、HEAD、单Range与OPTIONS；服务私有POST控制不能由携带浏览器Origin/Sec-Fetch的请求调用。资源只能读取当前固定媒体，不提供任意URL代理。上游签名、Cookie、密钥与明文媒体不落盘；资源读取、响应、缓存及尺寸均受界限约束。

## 生命周期与进度

隐藏时先暂停并卸载浏览器src，再suspend资源读取。已有上游读取最多等现有有界超时，取消代数下不得填新缓存或派生后续读取。恢复同一资源和实际位置但保持暂停，用户明确播放才继续。

切根页面、打开设置或退出时close所属会话与进程树。session跨进程启动随机化，checkpoint、close、suspend和resume核对代数；旧页面不能关闭新播放器或覆盖其进度。相同最终检查点不重复提交云端。生命周期动作保留用户倍速、音量与静音。

`LAZYBUDDY_CREDENTIAL_SCOPE`可隔离Windows凭据和设备目标，允许1–48个小写字母、数字或连字符；未设置时使用服务默认生产命名空间。真实宿主的数据目录与scope由宿主管理，不能因仓库整理复制凭据。测试使用显式独立目录及scope，不复用真实账号。

## 网络与故障诊断

服务启动时将所选http/https/all/no代理设置转给自身辅助进程，使Go与Python路由一致，保留显式环境覆盖。宿主「是否直连」清除本服务代理并设置`NO_PROXY=*`，关闭后重建服务跟随系统/环境设置；不修改机器或Clash配置，也不能据此声称绕过TUN路由。

取源前检查已验证端点，CDN逐跳校验HTTPS及允许来源，不附账号Cookie或网页Referer。错误细分为`media_redirect_https_required`、`media_redirect_target_rejected`、`media_redirect_missing_location`、`media_redirect_limit`；旧`media_redirect_rejected`仍可显示。不能为偶发故障放宽来源、增加自动重试或更换身份。手动重试由当前用户明确发起，保留当前剧与集的错误上下文。

`app_playback_empty_response`只表示播放模型阶段HTTP200但正文为空，此时尚无浏览器资源，不能靠更换解码器解决。目录成功、手机可播或网站已登录均不能证明桌面App取源权限；网络、身份和请求兼容原因需日志证据，不猜测为账号拒绝。偶发真实网络问题的当前结论与下一步只在TASKS维护。

设置`LAZYBUDDY_DATA_DIR`后，`logs/media.log`保存JSONL，单份128KiB、两个轮转备份，跨进程短锁保护。记录UTC时间、PID、阶段、剧/集、清晰度、direct/system、HTTP状态、跳转序号、来源/目标主机、异常类型和有限栈文件/函数/行号。错误码供界面快速定位，底部显示可理解的上下文；准确排查以脱敏日志为准。

不写完整URL、查询参数、响应正文、原始异常文本、局部变量、账号材料或媒体能力。记录失败不能破坏播放，日志不是新网络请求或自动重连依据。

## 定向验证

单位测试覆盖协议、会话、Range、取源和质量选择；具体入口由`scripts/check-changes.py`选择。不会读取真实凭据或访问真实节目。

浏览器合成fixture归本服务，独立生成后交给明确指定的外部宿主，不导入宿主源码：

```powershell
python -B scripts/verify/stage-browser-fixture.py --runtime-packages target/packages --output target/packages/browser-fixture
```

输入目录须含已独立生成并解包的`python-runtime/`运行时包；输出须是未存在的暂存目录。外部宿主显式设置`LAZYBUDDY_BROWSER_FIXTURE_FILE`指向自制4秒以上、最多8MB的MP4，目录按统一规范放`tmp/fixtures/media`，隔离配置和报告也归tmp。fixture不能发布为正式模块，也不能给生产入口增加任意账号或URL覆盖。

实际WebView验证应分开确认二维码取消、收藏反馈、真实帧推进/seek、隐藏停止读取、恢复暂停、切页失效旧资源及退出收尾。合成H.264/H.265/AAC成功不代表上游节目权限、真实音频质量或节目音画同步，单元成功也不替代这些验收。
