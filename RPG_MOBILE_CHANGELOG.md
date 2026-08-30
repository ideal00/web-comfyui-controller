# RPG Mobile Bridge 修改说明

## 本次完成

- RPG API 升级到 v2。
- 修复 ComfyUI 子目录输出导致手机端 404。
- 增加 requestId 幂等提交，避免移动网络重试重复生成。
- 增加按 requestId 恢复任务。
- 增加 `/api/rpg/capabilities`。
- 增加安全的输出图片路径解析。
- 增加 RPGBox TypeScript 手机客户端 SDK。
- RPG 专项测试：7/7 通过。
- 全项目测试：运行到 51 项无失败后，被当前执行环境单次命令时限中断，因此未声明全量通过。

## 推荐运行方式

Windows 下运行 `launchers/Start_EasyPanel_Mobile_RPG.bat`。手机与电脑同一局域网时，在 RPGBox 中填写脚本显示的 `http://电脑IP:8190` 和 Token。
