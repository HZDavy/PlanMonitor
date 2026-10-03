# Plan Monitor · 火山方舟 Coding Plan / Agent Plan 用量浮窗

一个轻量、可固定在副屏的桌面小工具,用于监控火山方舟 Coding Plan / Agent Plan 个人版的 AFP 额度用量(近 5 小时、近一周、近一月三个窗口)。

数据源:火山方舟 OpenAPI GetAFPUsage(Action=GetAFPUsage&Version=2024-01-01)。

官网:https://hzdavy.github.io/plan-monitor/

## 项目介绍

本工具的设计目标是「挂在副屏、看着余额用完」:

- 体积小巧:单文件约 41 MB,常驻内存约 8 MB,冷启动 < 1 秒
- 不打扰:不弹窗、不抢焦点、可置顶、可一键移到副屏
- 不联网:除官方 API 外无任何外发请求,AK/SK 只保存在本地 config.json
- 可视化:深色 vivo OriginOS 设计语言,长时间挂在副屏不刺眼

## 功能特性

- 三窗口监控:近 5 小时 / 近一周 / 近一月,已用量、配额、剩余量、剩余百分比、距离下次重置的倒计时
- 自动刷新:每 30 秒拉取一次;也可手动点右下角刷新按钮
- 凭据本地保存:AK / SK 仅保存到 config.json(同目录),不上传任何服务器
- 窗口置顶:支持「窗口置顶」和「移动到副屏」
- 深色 UI:默认深色主题,长时间挂在副屏不刺眼

## 截图示意

```
+--------------------------------------+
|  Coding Plan 用量      套餐 Large   |
+--------------------------------------+
|  近 5 小时   12.5 / 50               |
|  剩余 37.5    重置 4h 47m             |
+--------------------------------------+
|  近一周     150 / 500                |
|  剩余 350     重置 4d 7h              |
+--------------------------------------+
|  近一月     850 / 2000               |
|  剩余 1150    重置 26d 7h             |
+--------------------------------------+
|  设置   刷新   置顶   -> 副屏        |
+--------------------------------------+
```

## 安装

需要 Python 3.8+。

```bash
pip install PyQt5 requests
```

## 启动

```bash
python coding_plan_monitor.py
```

## 获取 Access Key

1. 打开 火山引擎访问控制 - Access Key 管理
2. 创建一个 Access Key(推荐使用子账号 AK,并仅授予 ArkReadOnlyAccess 权限)
3. 第一次启动后点击右下角「设置」,填入:
   - Access Key ID
   - Secret Access Key
   - (可选)Region,默认 cn-beijing
4. 点击「保存」,工具会自动请求一次并刷新界面

## 副屏固定使用

1. 把窗口拖到副屏上合适位置
2. 点击底部 「置顶」,窗口会保持在所有窗口最前
3. 点击底部 「-> 副屏」,窗口会立即移动到第一个外接屏幕
4. 下次启动时,窗口会恢复到上次位置和屏幕

## 文件

- coding_plan_monitor.py — 主程序(单文件可直接分发)
- config.json — 首次保存凭据后自动生成,存放 AK/SK(请勿上传到代码仓库)

## 鉴权说明(HMAC-SHA256)

火山方舟 OpenAPI 使用火山引擎标准的 HMAC-SHA256 V4 签名。本工具按官方规范生成:

```
StringToSign = POST + LF + application/json + LF + <sha256(body)> + LF +
               X-Date:<x-date> + LF +
               host:ark.cn-beijing.volces.com + LF + LF +
               ;host;x-content-sha256;x-date + LF +
               <sha256(canonical_request)>
```

详细实现见 Volcengine Signature V4。

## 安全提示

- 不要把 config.json 上传到 Git
- 推荐为监控单独创建一个 子账号 + AK,只授予读权限
- 如果不小心泄露了 SK,立即在控制台「删除 Access Key」

## License

MIT