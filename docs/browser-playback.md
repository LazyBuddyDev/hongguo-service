# 浏览器播放资源

红果服务负责身份、目录、单集权限、清晰度选择和有界媒体准备，输出受控的压缩MP4资源；浏览器负责解复用、解码、音画同步与呈现。服务不逐帧向JavaScript传像素，不自动转码。默认功能包只依赖私有Python及包内辅助程序，不要求GStreamer。构建见[README](../README.md)，账号方法见[业务API](module-api.md)，交付状态见[TASKS](../TASKS.md)。

## 私有控制协议

沿用API v1 JSON Lines，只有明确用户操作及当前可见页面所需请求可运行：

| 方法 | 参数 | 结果 |
| --- | --- | --- |
| `playback.open` | 字符串`series`、整数`episode`、可选字符串`quality`、可选布尔`refresh_catalog`、明确`origin` | 新会话代数与loading状态 |
| `playback.prefetch` | 当前整数`session` | 异步准备已验证目录中的唯一下一集，返回当前会话状态，不切换或暴露候选资源 |
| `playback.prefetch_cancel` | 当前整数`session` | 取消候选准备与缓存，不改变当前集 |
| `playback.status` | 无 | 当前loading/prepared/error、目录与资源 |
| `playback.report_error` | 整数`session`、浏览器媒体错误`code`（1–4） | 记录所属会话错误 |
| `playback.suspend/resume` | 整数`session` | 停止/允许资源读取，加载中suspend取消准备 |
| `playback.checkpoint` | `session`、秒数`position/duration`、可选布尔`final` | 保存真实观看断点，final请求提交 |
| `playback.close` | 整数`session` | 释放资源与输入进程，收尾已有进度事务 |
| `danmaku.read` | 当前已准备且未挂起的整数`session` | 首次调用后台读取当前集，轮询返回`pending`、`items`（`text`与毫秒时间`offset_ms`）或`error` |
| `danmaku.cancel` | 当前整数`session` | 取消弹幕读取并丢弃当前弹幕结果 |

从 0.2.19 起，播放状态声明 `danmaku: true`。弹幕使用已验证分集目录和已有设备档案读取，经独立任务处理。账号 Cookie 不参与弹幕取数。切集、关闭或挂起会取消任务并丢弃结果；上游仅返回精选数据，每集读取最多 32 个时间窗口、1200 条弹幕。

准备完成时返回`prepared: true`、`resource: {url, mime: "video/mp4"}`、`session`、`suspended`，以及脱敏错误、进度、分集与清晰度字段。`available_qualities`是数字数组（如`[360,720,1080]`），请求`quality`使用带p字符串（如`"720p"`），客户端在边界转换，不把旧集档位照搬给新集。档位来自当前集实际兼容结果。0.2.12起，保存的清晰度是偏好：优先选择达到偏好的最近兼容档位；若当前集最高兼容档位低于偏好，则从同一响应选择最高兼容档位，不额外重试请求。客户端显示实际视频尺寸对应的清晰度，保留用户偏好供后续剧集使用。

接受open不代表浏览器已解码。仅当前可见页面轮询准备状态；用`loadedmetadata`、实际尺寸、帧回调`mediaTime`、媒体error与真实EOS反馈播放。请求seek目标、滑块预览或服务声明时长不能代替已观看帧时间。

分集目录最多复用120秒。目标集缺失、手动重试同一失败集或明确传入`refresh_catalog: true`时重新读取目录；已验证设备档案可继续复用。

## 下一集准备

0.2.14起，客户端在当前集有实际播放帧后，每个会话最多调用一次prefetch；末集、暂停/隐藏及非活动页不派发。服务只接受所属当前session，按已确认可用目录选取紧邻下一集，沿用当前账号、清晰度偏好与Origin；在独立Job中验证该集身份/权限，异步取源并缓存前1MiB，包含媒体初始化信息。至多一个候选输入进程，不启动解码器、不全片下载、不落盘，也不生成候选观看进度。

下一次open只在剧、集、清晰度偏好、Origin及当前身份匹配时接用候选会话；候选仍准备中则继续等待同一次准备，不另起取源。真实EOS才允许自动切集，不用时间阈值推断结束。显式选集也可接用匹配候选；换剧/其他集/清晰度变化释放不匹配候选。原会话最终断点只提交一次，候选准备与真实观看记录分离。

suspend、close、账号切换及页面释放取消候选及其进程树；恢复不自动重新预加载或播放。预加载失败不改变当前播放；下一集被明确拒绝时保留失败到接用，不自动重试取源。取消代数后的结果不能恢复资源或填入新缓存。实际首帧切换仍包含浏览器加载/解码开销，不能宣称无缝切换。

## 本地媒体资源

URL为127.0.0.1上的随机短期会话能力，不是上游签名地址，不能持久化、输出到公开状态或日志。只允许open明确传入的Origin、精确Host及固定路径。浏览器使用CORS模式，例如`<video crossorigin="anonymous">`。

支持GET、HEAD、单Range与OPTIONS；服务私有POST控制不能由携带浏览器Origin/Sec-Fetch的请求调用。资源只能读取当前固定媒体，不提供任意URL代理。上游签名、Cookie、密钥与明文媒体不落盘；资源读取、响应、缓存及尺寸均受界限约束。

每个资源最多12个连接处理线程，其中最多4个可同时读取媒体。暂停、恢复和关闭在同一锁内更新读取状态与代数。

## 生命周期与进度

隐藏时先暂停并卸载浏览器src，再suspend资源读取。已有上游读取最多等现有有界超时，取消代数下不得填新缓存或派生后续读取。恢复同一资源和实际位置但保持暂停，用户明确播放才继续。

切根页面、打开设置或退出时close所属会话与进程树。session跨进程启动随机化，checkpoint、close、suspend和resume核对代数；旧页面不能关闭新播放器或覆盖其进度。相同最终检查点不重复提交云端。生命周期动作保留用户倍速、音量与静音。

`LAZYBUDDY_CREDENTIAL_SCOPE`隔离Windows凭据和设备目标，允许1–48个小写字母、数字或连字符。`LAZYBUDDY_INSTANCE`为`default`或未设置时可使用默认凭据空间，也可由宿主指定其既有的`shell-preview`。其他实例必须显式指定独立scope，并使用独立数据目录。

已有桌面安装需要同时更新宿主与0.2.18服务。更新后的宿主继续使用既有生产凭据空间，并仍可连接0.2.17服务。

## 网络与故障诊断

服务启动时将所选http/https/all/no代理设置转给自身辅助进程，使Go与Python路由一致，保留显式环境覆盖。宿主「是否直连」清除本服务代理并设置`NO_PROXY=*`，关闭后重建服务跟随系统/环境设置；不修改机器或Clash配置，也不能据此声称绕过TUN路由。

取源前检查已验证端点，CDN逐跳校验HTTPS及允许来源，不附账号Cookie或网页Referer。错误细分为`media_redirect_https_required`、`media_redirect_target_rejected`、`media_redirect_missing_location`、`media_redirect_limit`；旧`media_redirect_rejected`仍可显示。不能为偶发故障无条件放宽来源、增加自动重试或更换身份。手动重试由当前用户明确发起，保留当前剧与集的错误上下文。

初始片源只接受 HTTPS 的 `*.qznovelvod.com`。已验证的调度源为 `v<数字>-reading-video` 与 `v<数字>-ex-reading-video`，两者均允许无后缀、单字母后缀、`cdn` 或 `cdn302`。外部 CDN 仅接受当前请求的原始调度源委派。委派目标为单个 40–63 位字母数字节点下的 `vegslb.com` 或 `bdcgslb.com`，以及单个 40–63 位十六进制节点下的 `v.smtcdns.com`。编号、已支持的后缀和节点标识变化不需要逐个登记。未知调度源、未知 CDN 域或不符合格式的节点继续拒绝。直连和代理共用校验，均绑定不可变的初始来源，逐跳保留 HTTPS 证书、443 端口、无用户信息、无片段及跳数限制。媒体请求保留 Range 和响应尺寸校验，不附账号凭据。

遇到新跳转拒绝时，从宿主脱敏日志提取同一事件的来源、目标和跳数，并与历史记录去重。新增经过核实的调度源或 CDN 类型时，回归同时覆盖所有已知拒绝链路、合法命名变化和未知目标拒绝，直连和代理均需验证。原失败剧集的实际播放须单独验证，取得不同 CDN 节点时如实记录。

`app_playback_empty_response`只表示播放模型阶段HTTP200但正文为空，此时尚无浏览器资源，不能靠更换解码器解决。目录成功、手机可播或网站已登录均不能证明桌面App取源权限；网络、身份和请求兼容原因需日志证据，不猜测为账号拒绝。偶发真实网络问题的当前结论与下一步只在TASKS维护。

0.2.11起服务不写日志，不接收宿主日志路径；`diagnostics.py`只构造有界、脱敏的API诊断。同步错误通过`error.diagnostic`返回；私有取源子进程的失败诊断经媒体状态透传为`data.diagnostic`，调用方决定是否记录。字段含阶段、剧/集、清晰度、连接模式、HTTP状态/字节/读取结果及有限代码位置。服务不感知调用方是不是桌面宿主，普通CLI调用同样只收到结构化结果。

不写完整URL、查询参数、响应正文、原始异常文本、局部变量、账号材料或媒体能力。记录失败不能破坏播放，日志不是新网络请求或自动重连依据。

## 定向验证

单位测试覆盖协议、会话、Range、取源和质量选择；具体入口由`scripts/check-changes.py`选择。不会读取真实凭据或访问真实节目。

浏览器合成fixture归本服务，独立生成后交给明确指定的外部宿主，不导入宿主源码：

```powershell
python -B scripts/verify/stage-browser-fixture.py --runtime-packages target/packages --output target/packages/browser-fixture
```

输入目录须含已独立生成并解包的`python-runtime/`运行时包；输出须是未存在的暂存目录。外部宿主显式设置`LAZYBUDDY_BROWSER_FIXTURE_FILE`指向自制4秒以上、最多8MB的MP4，目录按统一规范放`tmp/fixtures/media`，隔离配置和报告也归tmp。fixture不能发布为正式模块，也不能给生产入口增加任意账号或URL覆盖。

实际WebView验证应分开确认二维码取消、收藏反馈、真实帧推进/seek、隐藏停止读取、恢复暂停、切页失效旧资源及退出收尾。合成H.264/H.265/AAC成功不代表上游节目权限、真实音频质量或节目音画同步，单元成功也不替代这些验收。

### 空响应与有限响应头诊断

0.2.10的取源失败诊断在`response_meta`中仅保留白名单：HTTP版本枚举、Content-Type类别（去参数）、Content-Encoding类别、声明长度、Go自动解压布尔值、Transfer-Encoding类别、服务端Date与本机的秒差，以及请求ID/Location头是否存在的布尔值。未知文本只记other，不记录任意响应头原文、Set-Cookie、请求ID值、Location地址或响应正文。Python诊断构造端再次校验枚举、数值范围和类型。自动解压时Go可能移除原Content-Length/Content-Encoding，需结合uncompressed解释，不能将读取后的字节数冒充原始线路字节数。

请求核对使用vendor/openhongguo/BRIEFDOCK.md所列固定版本第三方参考（不是官方API规范）：GET路径、业务字段、应用版本73932，以及query的_rticket与签名头时间同源。当前未确认服务端实时验签/放行要求。未引入参考中的身份轮换、跨主机回退或自动重试。发现SDK空CSRF占位与账号Cookie直接追加会重名，现按Cookie名称合并，账号值覆盖同名占位，保留现有设备的install_id/ttreq；这修复了请求构造风险，但尚无真实请求证据证明它是原200空体的根因。

收藏封面自0.2.13起按剧ID的哈希读取有界像素缓存，服务重建丢失来源表时仍可返回已缓存图片；未缓存或过期/损坏的图片且无已验证来源时返回cover_unavailable，不新增来源查询或自动刷新收藏。搜索封面沿用已有来源缓存，接口不暴露封面地址。
