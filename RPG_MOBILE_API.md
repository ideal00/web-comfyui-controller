# Easy Panel × RPGBox 手机生图接口（API v2）

Easy Panel 现在可以作为 RPGBox 的视觉后端。手机只访问 Easy Panel `8190`，Easy Panel 再在电脑本机访问 ComfyUI `8188`。

当前配套版本：Easy Panel 服务端 `2.1.0`，Android 客户端 `mobile-v1.3.0`（versionCode `1003000`）。协议仍为 RPG API v2。

## 1. 启动手机模式

运行：

`launchers/Start_EasyPanel_Mobile_RPG.bat`

脚本会：

- 让 Easy Panel 监听 `0.0.0.0:8190`；
- 保持 ComfyUI 为 `127.0.0.1:8188`；
- 创建 `rpg_mobile_token.txt`；
- 显示电脑局域网 IP 和 Token。

手机与电脑处于同一局域网时，RPGBox 使用类似 `http://192.168.1.10:8190` 的地址。

> 不建议把 8190 直接裸露到公网。跨公网使用时请放在 VPN / Tailscale / HTTPS 反向代理之后。

## 2. 鉴权

除 `/api/rpg/ping` 外，RPG API 请求需要：

`X-RPG-Token: <rpg_mobile_token.txt 中的内容>`

也支持：

`Authorization: Bearer <token>`

远程访问 Easy Panel 的完整网页、旧版 `/api/*`、快照详情/对比和 `/output` 也需要同一个 Token。桌面浏览器第一次收到 HTTP Basic 鉴权挑战后，可将 Token 填入密码完成会话；服务器只返回短时 HttpOnly、签名 Cookie。Android 高级 WebView 只在首次根页面请求通过原生 `X-RPG-Token` 请求头引导该会话，Token 不会出现在 URL、网页 JavaScript 或 localStorage 中。局域网/ Tailscale 仍建议只在私网内开放 8190。

## 3. 连通性

### GET `/api/rpg/ping`

返回：

```json
{
  "ok": true,
  "api_version": 2,
  "service": "ComfyUI Easy Panel RPG Bridge",
  "token_required": true
}
```


### GET `/api/rpg/capabilities`

返回手机端可用能力、推荐轮询间隔和尺寸限制。RPGBox 可用它判断服务端是否支持 `requestId` 去重、任务恢复、子目录图片等能力。

### GET `/api/rpg/jobs/by-request/{requestId}`

用于手机切后台、切网络或 App 重启后的任务恢复。`requestId` 应由 RPGBox 在第一次提交前生成并持久化。

### GET `/api/rpg/models`

返回 Easy Panel 当前实际可用的 Checkpoint、Anima、Krea 2 模型。

### GET `/api/rpg/profiles`

读取 `rpg_visual_profiles.json`。

### POST `/api/rpg/profiles`

保存角色视觉配置。

## 4. 生成剧情 CG

### POST `/api/rpg/generate`

最小请求：

```json
{
  "client": {
    "gameId": "demo",
    "sceneId": "chapter1_turn15",
    "requestId": "demo_chapter1_turn15"
  },
  "visual": {
    "characters": [
      {
        "id": "luna",
        "expression": "shy, blush",
        "pose": "standing",
        "action": "looking away"
      }
    ],
    "location": "school rooftop",
    "time": "sunset",
    "shot": "cowboy shot",
    "lighting": "warm rim light"
  },
  "generation": {
    "seed": -1
  }
}
```

模型可省略：Easy Panel 会优先选择 WAI / Spectacular / Illustrious 系模型；也可指定：

```json
"generation": {
  "model": "waiIllustriousSDXL_v140.safetensors",
  "width": 832,
  "height": 1216,
  "seed": -1,
  "regional": false
}
```

`requestId` 是幂等键：同一个 `requestId` 因网络超时而重复 POST 时，Easy Panel 会返回已有任务，不会再次提交 ComfyUI。

提交成功：

```json
{
  "api_version": 2,
  "job_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "status": "queued",
  "status_url": "/api/rpg/jobs/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
}
```

## 5. 查询任务

### GET `/api/rpg/jobs/{job_id}`

生成中：

```json
{
  "job_id": "...",
  "status": "running",
  "images": []
}
```

完成：

```json
{
  "job_id": "...",
  "status": "completed",
  "images": [
    {
      "filename": "RPGBox_demo_chapter1_turn15_00001_.png",
      "url": "/api/rpg/image?name=RPGBox_demo_chapter1_turn15_00001_.png"
    }
  ]
}
```

RPGBox 应把相对 `url` 拼到 Easy Panel Base URL，然后带同一个 Token 下载图片。

## 6. 角色 LoRA / 固定服装

编辑 `rpg_visual_profiles.json`：

```json
{
  "version": 1,
  "defaults": {
    "model": "waiIllustriousSDXL_v140.safetensors",
    "width": 832,
    "height": 1216,
    "safetyLevel": "safe",
    "style": "",
    "negative": "",
    "regional": false
  },
  "characters": {
    "luna": {
      "name": "Luna",
      "gender": "female",
      "trigger": "luna",
      "appearance": "grey hair, short hair, bob cut, blue eyes, pink x-shaped hairclip",
      "loras": [
        {"name": "characters/luna.safetensors", "weight": 0.9}
      ],
      "default_outfit": "default",
      "outfits": {
        "default": "blue cropped top, cropped jacket, blue shorts, white thighhighs",
        "maid": "maid, maid headdress, white apron, frilled apron"
      }
    }
  }
}
```

之后 RPGBox 只发：

```json
{"id":"luna","outfit":"maid","expression":"smile"}
```

Easy Panel 自动补角色 LoRA、外貌和服装，再交给原有模型提示词编译器。

## 7. 双人 Regional Prompting

两名角色时可设置：

```json
"generation": {"regional": true}
```

Easy Panel 会调用项目现有的 Regional Prompting 路线，把两名角色分到左右软区域。每个角色配置的第一项 LoRA 会作为对应区域绑定 LoRA。Anima / Krea 2 会继续遵守项目原有限制，不允许 Regional Prompting。

## 8. Android 注意事项

如果 RPGBox Android 使用 `http://192.168.x.x:8190`，Android WebView/Capacitor 需要允许局域网明文 HTTP（cleartext traffic）。更稳妥的长期方案是给 Easy Panel 加 HTTPS / Tailscale。

推荐交互顺序：

1. RPGBox 先显示 LLM 剧情；
2. 异步 POST `/api/rpg/generate`；
3. 每 1.5~2 秒查询 `/api/rpg/jobs/{id}`；
4. `completed` 后下载图片并缓存到 Android 本地；
5. 断网/切后台后用保存的 `job_id` 继续查询。


## 9. API v2 移动端可靠性修正

- 支持 `client.requestId` 幂等提交，避免弱网重试重复生图。
- 支持 `/api/rpg/jobs/by-request/{requestId}` 恢复任务。
- 图片 URL 会保留 ComfyUI `subfolder`，输出到子目录也能下载。
- 图片下载会验证最终路径仍位于 ComfyUI output 目录内，阻止目录穿越。
- 附带 `rpgbox_mobile_sdk/`，可直接复制进 RPGBox React/Capacitor 项目。

## 10. 生成快照与恢复

- `/api/rpg/snapshots` 只返回摘要；`/api/rpg/snapshots/{id}` 在鉴权后返回完整可恢复记录。
- Web 完整面板的 `/api/snapshots`、`/api/snapshot-compare` 和 `/output` 也受面板鉴权保护，不能通过无 Token 的远程请求读取完整提示词、生成参数或图片。
- Android 的“完整恢复”会附加服务器记录的 LoRA、采样、区域和增强配置；“只换 Seed”只改 Seed；“继续编辑”保留该附加配置并允许修改当前可见字段。
- Android 点击“解除快照高级配置 / 转为普通生图”后，仅提交当前可见的普通生图字段，不再隐式带上旧快照高级参数。
