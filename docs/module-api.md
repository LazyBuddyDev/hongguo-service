# 红果服务 API

API v1，Windows x64。服务独立提供账号、搜索、官方收藏、观看进度、封面与媒体资源；不依赖宿主GUI。通用清单及JSON Lines约定见[宿主模块契约](https://github.com/LazyBuddyDev/LazyBuddy/blob/main/docs/module-api.md)，构建入口见[README](../README.md)。

stdin每行一个UTF-8请求，如`{"version":1,"id":"h1","method":"health","args":{}}`。回复保留`version/id`，使用`ok:true,data`或`ok:false,error:{code}`。关闭stdin时停止派发新的云端写入，已开始的写入及确认共用5秒收尾预算，未确认进度保留在本地。

## 业务方法

| 方法 | 参数 | data |
| --- | --- | --- |
| `health` | 无 | `service: "hongguo"`、`api_version: 1`及能力声明 |
| `search` | `query`、`page` | `items`、`page`、`has_more` |
| `account.restore/status/login/cancel/logout` | 无 | `state`、`name`、`qr_png`、错误与事务字段 |
| `favorites.read` | 无 | pending事务，之后返回官方确认的`favorites` |
| `favorites.set` | 十进制字符串`series`、布尔`favorite` | pending事务，之后返回官方读回或`favorites_error` |
| `progress.read` | 无 | 账号隔离的`history`与同步状态 |
| `progress.sync` | 无 | pending事务，之后返回`history`、`sync_state`、`sync_error` |
| `cover.read` | 已知字符串`series` | `series`、`width`、`height`、Base64 `rgba` |
| `work.begin` | `method`、`args`，支持搜索、封面、账号恢复及取消扫码 | 整数`job` |
| `work.status` | 整数`job` | `pending: true`或一次性`reply`，后者包含原业务回复 |
| `work.cancel` | 无 | 取消当前连接的所有后台任务 |
| `lifecycle.suspend` | 无 | 完成媒体/账号收尾，返回`suspended` |

列表项包含字符串`id`、`title`、总`episodes`、`has_cover`。封面最多240×360 RGBA，客户端校验尺寸、Base64上限和字节数；服务只接受已知剧集ID，不接受任意图片URL。

后台任务最多8个，搜索同时最多1个，任务60秒过期。页面代数变化时客户端取消并丢弃旧任务结果。升级前的服务会对`work.begin`返回`unknown_method`，客户端可调用原有同步方法。

## 登录与事务

`qr_png`是Base64 PNG，不在二维码阶段时为空。状态包括`idle`、`preparing`、`pending`、`scanned`、`verifying`、`signed_in`、`failed`、`cancelled`。只有身份验证和安全保存均完成才显示已登录；cancel停止本次扫码，logout才删除本应用保存的身份。原始账号标识、设备档案、Cookie、Token、签名地址和密钥不公开。

耗时收藏读写及进度同步返回`operation: "pending"`与`operation_method`，客户端通过`account.status`接收完成结果。期间`progress.read`仍可读取本地状态，其余账号操作可能返回`account_busy`。收藏响应声明还有分页或数量不全时，保留上次完整列表并报告失败。收藏乐观反馈与官方确认列表分离，失败或取消时恢复反馈。已提交事务离开后可能仍完成。

扫码只在可见二维码视图轮询，离开停止；非当前页面不能续期账号、同步收藏或预加载。关闭服务等待已提交事务收尾，不中断为未完成的事务保存。凭据仅使用Windows安全存储；独立验证使用独立数据目录和`LAZYBUDDY_CREDENTIAL_SCOPE`，规则见[浏览器播放](browser-playback.md)。

## 观看进度

历史按字符串剧ID索引，包含`episode`、秒数`time`与Unix秒`updated`。恢复账号读取本地快照，可见客户端再显式同步云端；合并按更新时间，包括较新的回退，不按最大集号或位置。播放/加载期间主动云同步可能返回`player_busy`。

仅真实观看帧形成检查点，播放中保存本地，最终动作使用已提交的检查点收尾。回读必须匹配分集资源ID、集号、位置及服务端精度下的时间戳才确认上传。历史最大1 MiB，超限时优先移除最早的已确认或旧版记录，保留待上传项。测试使用独立凭据空间及合成响应。

## 媒体

Web消费者使用[浏览器播放资源API](browser-playback.md)：`playback.open/status/report_error/suspend/resume/checkpoint/close`。健康能力`browser_resources`和`credential_scopes`表明对应协议可用，不等于某部剧有权播放或已经成功解码。

独立服务仍保留可选`media.*`原生解码能力，见[可选原生媒体运行时](media-runtime.md)；当前Web宿主不使用，默认包不依赖该运行时。不要混合两条呈现路径的验收结果。

## 封面缓存

0.2.8起，cover.read在确认该剧已有受控来源后复用`LAZYBUDDY_DATA_DIR/cache/covers`中的解码图片。文件名为完整来源字符串的SHA256，不保存URL/签名参数，文件只含宽高及有界RGBA；最多64张、7天有效，来源变化产生新键，损坏或过期重新获取。写入原子替换、短锁保护轮转，缓存故障不阻断已成功获得的封面。前端另有按当前账号展示生命周期隔离的64张内存缓存，退出/重新登录清空，不在隐藏时续取。

## 结构化失败诊断

0.2.11起服务只返回诊断而不记录日志。同步失败可带`error.diagnostic`；异步取源失败在`playback.status`的`data.diagnostic`保留同一诊断。仅包含白名单上下文/HTTP元数据/有界栈位置，不携带原始异常文本、请求地址或秘密。调用方自行决定日志路径、格式及生命周期，服务没有宿主日志目录配置。
