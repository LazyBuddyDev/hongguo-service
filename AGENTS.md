# hongguo service development

文件归位与命名遵循[文件放置规范](https://github.com/LazyBuddyDev/LazyBuddy/blob/main/docs/file-layout.md)，路径相对本服务仓库；接口入口见[本服务API](docs/module-api.md)。


- This repository owns its business API and build/package tests. Do not import desktop implementation or require a sibling workspace checkout. All external integration uses versioned API, staged packages and explicitly supplied host binaries.
- TASKS.md contains only unfinished goals and the current facts, remaining TODOs, owner/version, necessary evidence, blockers and next step needed for handoff. One complete goal has one stable ID; phases are internal steps. Remove completed or fully superseded entries without an archive; compare all remaining goals before merging partial overlaps. Do not create entries for scripts, rules, commits or synchronization alone. Use literal `[x]` for pending and `[√]` only for necessary completed steps inside a current task.
- Add focused unit/contract tests for non-trivial behavior; use fixtures by default. Do not turn a local change into a full real-account acceptance run. Network/identity/permissions and synthetic/real decoding evidence remain separate.
- Prefer CLI, simple existing code and standard libraries. Research difficult integration against official upstream examples before adding abstractions. Keep UI out of the service, and preserve validation at credentials, network, IPC and local-file boundaries.
- Credentials, device identities, signed URLs and media keys never enter commits, command arguments or public errors. Explicit user authorization is required for real account writes. Do not infer rights from a successful login or one episode.
- Use private dependencies and ignored target/tmp output. Clean verified obsolete artifacts promptly, preserving SDKs, live instances, source and unpushed Git history. Do not run a blanket clean against a shared SDK.
- Confirm own-code and third-party licenses before public distribution. Preserve upstream notices; do not invent a license or release identity. Commit/push/transfer/tag/release are separate actions within current authorization.


## 文档维护

- 根README只放产品介绍与快速入口，docs/README维护专题导航，AGENTS只放长期约束，功能进度归TASKS；具体归位按文件放置规范执行，不重复维护目录表。
- 一个主题只保留一份权威说明。宿主维护通用协议，各服务维护自己的业务API，跨仓库使用明确链接，不复制整份文档；说明当前实现；TASKS仅保留未完成任务接手所需证据，长期结论归专题，不维护已完成任务历史。
- 专题文件名使用稳定英文kebab-case，不追加日期、版本或阶段；小规模专题保持平铺。新增、合并或删除文档时同步导航、README和所有有效引用，命令路径相对所属仓库，不写开发机固定路径或凭据。
- 一次性报告、截图和录屏放已忽略的tmp，长期结论归并专题；公开站点和签名机器端点另有用途，不作为普通文档删除或格式化，签名内容保留精确字节。
- 纯文档修改检查链接、示例入口与已发布文件的字节完整性，不默认运行全量功能测试；构建通过、样例通过和真实验收分开报告。


## 红果账号与媒体

- 账号、媒体目录、单集权限、收藏读写和观看进度分别验证，身份恢复或首集可播不能外推其他能力。凭据仅在Windows安全存储，按账号隔离设备档案、收藏和历史；公开CLI/API不输出Cookie、Token、原始账号标识、签名地址或密钥。
- 首次扫码由当前宿主内二维码弹层展示；只有身份核对及安全保存均成功才显示已登录。取消扫码、停止验证与明确退出账号不同；退出才删除本应用保存会话。切账号清空旧展示，旧代结果不能串号。预览实例显式指定凭据scope和独立数据目录，安全存储自检使用独立QA目标并收尾删除，不覆盖真实身份。
- 收藏来自官方账号，不能以本地列表冒充。读取结构、完整分页、增删和官方读回分别验收；异常结构不当作空列表，失败保留同账号已确认数据。星标乐观反馈与确认列表分离，失败或取消回滚反馈；请求期间禁重复写入，不自动重复提交。
- 耗时收藏读写异步返回pending，由账号状态获取官方确认，不能占住媒体暂停等控制。离开后只允许已提交事务完成当前核对，不派生下一轮；进度或其他写权限不能代替收藏许可。
- 观看记录按账号原子保存，按明确更新时间合并云端，云端较新的回退也应恢复；不能按最大集号/位置选新值。仅真实观看位置和已验证目录分集标识可上传。官方读回匹配前保留待上传状态，读取不完整或失败不覆盖本地文件，不将保存失败冒充退出登录。
- 账号恢复或重新进入列表核对云端；点击观看使用已有快照，不等云端队列。播放中只保存本地检查点，不周期联网；暂停、关闭、隐藏或离开时提交最终断点，没有变化不重复请求。网络锁不能阻塞新的本地真实记录，旧上传不能将更新的断点标成已同步。
- 取源及辅助进程归自身Windows Job，独立服务运行也不能遗留子进程。限定已验证端点和HTTPS/CDN来源，逐跳检查；CDN不携带账号Cookie或网页Referer。401/403后停止该源，不扩大白名单、轮换设备或更换身份试探权限。
- 媒体/账号密钥与明文媒体不落盘、不进命令行；私有回环只提供固定资源和受限Range，不成为任意URL代理。元数据、响应、解码尺寸、内存和缓存均有界，按需Range取数，不新增未要求的下一集预加载。
- 宿主不链接GStreamer；控制消息与共享纹理分开。解码fence在后台等待，GPU完成复制后才确认生产端释放；宿主保留自己的帧。纹理导入失败须反馈并停止媒体，不能黑屏继续无声报错。画面、透明度、真实seek、持续解码及EOS分别验证，不能只看字段。
- 浏览器输出以playback会话提供受控的压缩Range MP4，服务不解码；浏览器管理播放与实际帧时间。随机本地资源URL限明确Origin、Host和固定资源，不能变任意代理；URL不进日志，原始片源/身份/密钥不公开。隐藏后停止读取并丢弃取消代数下的新缓存，恢复须显式授权；checkpoint/close/suspend/resume核对会话代数，避免旧页面影响新播放器。原生media API为迁移期显式能力，浏览器模块不强制安装media-runtime；候选包发布前核对宿主协议与验证范围。
- 隐藏/最小化/胶囊仅暂停已建立管线，恢复不自动播放、不重新取源；加载中则取消。切页/设置释放管线，保留剧、集和真实位置，用户明确继续再载入。所有生命周期动作保留用户静音，音量为零不能改写mute；清晰度、所选倍速、音量和静音跨集/重启保留。
- 用户主动观看或切集完成取源后播放；生命周期恢复不自动播放。自动播放、seek、EOS和临时加速绑定当前请求代数。自动连播只接受当前真实EOS，按可用列表进入下一集，末集停止，不靠时间接近片长推测。
- 清晰度按该集实际兼容档位选择并显示实际尺寸，不能从声明或旧集推定高清成功；普通与临时倍速保持音高，seek保留既有结束位置。音频验证使用与产品相同的封装/解复用路径，测实际PCM时长和频率；音画同步不能由单项成功外推。
- 客户端界面规范由[宿主维护指南](https://github.com/LazyBuddyDev/LazyBuddy/blob/main/AGENTS.md)维护，本服务不复制GUI实现约束；控件显隐不应导致服务重建媒体或重新取源。
- 客户端播放控件和CLI使用同一服务操作；进度拖动只预览、松手提交一次，键盘/滚轮仍提交；暂停/离页清理预览，不用旧管线零值覆盖目标位置。控件显隐、窗口缩放只改布局，不恢复账号、重取源或重建管线。
- 空格切换播放，左右跳5秒；右键按住400ms临时2倍速，松开恢复所选倍速且不再跳转，暂停时不自动播放。控件捕获和热键录入优先；失焦、切页、收起、暂停和换集清理按住状态，不能留下临时倍速。


- 新增功能必须附带该功能的单元测试；日常只运行新增或受影响的测试与必要构建，不默认执行全部单元、真实接口、媒体或GUI回归。仅关联共享边界或失败证据需要时扩大验证，全量验收由用户明确要求。
