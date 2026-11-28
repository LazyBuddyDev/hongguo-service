# 本地签名运行时

自红果 0.2.20 起精确依赖 `hongguo-signer` 0.1.0，沿用宿主的依赖下载、校验和原子激活协议。签名运行时包含 openhongguo-signer、依赖 JAR 和私有 Java 21 镜像；用户无需安装系统 Java 或 Docker。基础宿主无需此运行时。

## 调用与生命周期

宿主通过 `LAZYBUDDY_DEPENDENCY_HONGGUO_SIGNER_DIR` 传入安装目录。服务首次需要 resolver 时在后台启动单个 signer，随机选择 IPv4 回环端口，生成只保存在内存、私有管道及子进程环境中的 token。健康检查最多等待 60 秒。实例由 Windows Job 持有，服务退出时连同 Java 退出；健康接口不启动 signer。账号与媒体输入共享服务内实例，媒体输入的私有管道接收临时连接参数，主协议线程不等待 Java 初始化。Java 使用独立临时工作目录，退出时清理，不向不可变模块目录写文件。

resolver 仅在原有端点校验通过后调用 `POST /feature-hash`，发送完整原始 URL 和实际正文的十六进制表示。签名服务能看到 URL 中的设备标识，但不会收到账号 Cookie。只接受六个签名头，不接受服务返回的 Cookie、Host 或其他任意头；响应最多 64 KiB，单次调用最多 5 秒，不跟随重定向、不走系统代理。签名失败停止原请求，不回退旧签名、不轮换设备或身份。设备注册请求保持原协议。

开发与诊断可显式设置 `LAZYBUDDY_HONGGUO_SIGNER_URL`（根地址）及 `LAZYBUDDY_HONGGUO_SIGNER_TOKEN`，此时使用外部实例，不启动打包的 Java。HTTP 只允许回环地址，远程必须 HTTPS。不要把 token 写入命令行或提交。旧的无运行时源码调用在未配置地址时保留原行为；完整新包通过精确依赖提供本地 signer。

## 构建

上游接口见 [openhongguo-signer](https://github.com/beilunyang/openhongguo/tree/32d2a8c6387d4a63fe9262525531dd9d363f9833/signer)。构建输入是该固定版本源码和经过发行方 SHA-256 校验的 Windows x64 JDK 21，均放在服务私有 `target` 下。

```bash
python -B scripts/prepare-hongguo-signer.py \
  --source target/tools/signer-source/openhongguo-32d2a8c6387d4a63fe9262525531dd9d363f9833 \
  --jdk target/toolchains/signer-java/jdk-21.0.13.1+2
python -B scripts/package-modules.py --output target/packages/signer-candidate
```

准备脚本以 Gradle 构建 JAR，用 jlink 生成精简 Java 镜像，不修改系统 Java。默认打包包含 hongguo、python-runtime、hongguo-signer；准备失败不应发布缺少运行时的包。运行时保留 Java legal/NOTICE、上游源码与许可。上游项目声明 Apache 2.0；其自带 App 原生库的再分发授权已由维护者在本次完整发布中确认，不将其表述为本项目原创。Java 遵循 GPLv2 + Classpath Exception，完整对应源码 `OpenJDK21U-jdk-sources_21.0.13.1_2.tar.gz` 随红果 v0.2.20 Release 独立提供，保留运行时 legal/NOTICE；JAR 依赖的许可证保留在各 JAR 内。

离线测试覆盖精确签名字节、凭据隔离、恶意响应、失败不回退、懒启动与退出回收。Windows 实际签名、完整包安装和真实节目播放分别验收；签名返回成功不能证明原 HTTP 200 空体问题已经解决。
