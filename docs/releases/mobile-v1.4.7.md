# Easy Panel Android 1.4.7

配套服务端 **2.3.0**。versionName **1.4.7**，versionCode **1004007**，Debug 包名 `app.rpgbox.mobile.debug`。

- 作品库上一页 / 下一页与页码跳转，保留筛选条件。
- 缩略图按可见区域加载，使用有界缓存。
- 高级面板复用已有 Token 会话，作品库无需重复登录。
- 高级面板随服务端升级获得创作游乐场、分区搜索与预设例图。

下载 `app-debug.apk`，校验文件为 `app-debug.apk.sha256`。本版为 Debug 测试签名 APK；覆盖安装要求与旧版签名相同。源码构建与 GitHub Actions 构建的 Debug 签名可能不同，安装前备份客户端设置。

验证范围：TypeScript / Web 生产构建、Vitest / Node、Capacitor 同步、Android 原生单测、Gradle APK 构建与 APK 版本 / 签名检查。未进行 Android 真机安装、系统下载与实际 GPU 出图验收。

[安装与连接教程](https://github.com/ideal00/web-comfyui-controller/blob/mobile-v1.4.7/android-client/README.md) · [电脑 / 手机功能对照](https://github.com/ideal00/web-comfyui-controller/blob/mobile-v1.4.7/docs/FEATURE_MATRIX.md)。
