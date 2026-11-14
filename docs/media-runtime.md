# 可选原生媒体运行时

本服务保留独立`media.*`解码能力，供明确实现原生消费者的客户端使用。当前LazyBuddy Web宿主仅消费[浏览器资源](browser-playback.md)，不链接GStreamer、不接收共享纹理；默认红果包不要求media-runtime。本文不是当前宿主接入指引，历史宿主实验和验收记录见[TASKS](../TASKS.md)。

## 协议与构建

可选worker使用固定GStreamer 1.26.11，控制消息与D3D12 IPC共享纹理分离。调用仍通过[私有JSON Lines](module-api.md)：

| 方法 | 参数 |
| --- | --- |
| `media.open` | `series`、`episode`、`quality`、`pipe`及可选`position/volume/mute/speed` |
| `media.play/pause/status/close` | 无 |
| `media.seek/speed/boost/volume/mute` | `value` |

具体状态与边界由`src/lazybuddy_hongguo/media.py`及worker实现定义。加载异步返回loading；换集取消旧取源和解码，并绑定请求代数。状态中的声明尺寸与`decoded_width/decoded_height`实际协商尺寸分别处理，不能用声明证明已输出图像。

构建使用本服务的`scripts/prepare-media-sdk.ps1`与`target/sdks/gstreamer`，显式打包选择`--modules media-runtime`；其余打包要求见[README](../README.md)。运行时包只含必要播放插件、依赖DLL与许可，清单保存在`runtime/playback-files.json`，SDK头文件和构建缓存不分发。

## 消费者责任

消费者后台等待解码fence，GPU复制完成后才确认生产端释放；显示保留自身纹理，不能仅凭控制回复或无报错推断画面成功。导入失败须反馈并停止媒体。管线、代理及取源辅助进程归所属Windows Job，退出不遗留进程。

已加载管线隐藏时暂停，恢复不自播；加载中取消。离开页面释放所属管线。媒体密钥、上游签名URL和原始帧不进入公共控制消息或日志。已提交账号事务的收尾不能阻塞暂停等控制。

## 可复用的开发经验

- 音频链为`audioconvert ! scaletempo ! audioresample ! autoaudiosink`；倍速保音高参见[GStreamer scaletempo](https://gstreamer.freedesktop.org/documentation/audiofx/scaletempo.html)。正向seek使用SET开始位置、NONE结束位置，避免截短播放段；非默认倍速或跳转等待有界preroll。
- 合成音频使用与产品相同的MP4/qtdemux链。AVI push-mode样例的demuxer可能重置rate，不能用它推断生产MP4变速失败。AAC样例编码前转换为编码器要求的格式，不能将样例编码故障记为产品解码问题。
- 依赖DLL闭包使用微软[DUMPBIN /DEPENDENTS](https://learn.microsoft.com/en-us/cpp/build/reference/dependents?view=msvc-170)，动态加载入口和插件另列为根，静态导入闭包不能证明所有动态能力完整。
- 实际尺寸读取[GStreamer当前协商caps](https://gstreamer.freedesktop.org/documentation/gstreamer/gstpad.html#gst_pad_get_current_caps)，释放取得的引用，不以模型声明冒充实际输出。

协议、三帧像素、暂停/真实seek/EOS、音频PCM时长与频率、完整消费者呈现分别验证。相关服务驱动在`scripts/verify/`，外部探针通过`LAZYBUDDY_HOST_DIR`显式提供，已删除的旧Iced探针不能当作当前宿主可用命令。合成验证不代表真实节目编码、权限或音画同步通过。
