## Plan Monitor · 首发版本

一个约 8 MB 内存常驻的 Windows 浮窗,实时显示火山方舟 Coding Plan / Agent Plan 的剩余用量。

### 核心功能

- 三档时间窗:5 小时 / 1 周 / 1 月 用量实时显示
- 30 秒自动刷新 火山方舟 Coding Plan / Agent Plan API
- 深色玻璃风 PyQt5 浮窗,vivo OriginOS 设计语言
- 霓虹绿渐变 m 任务栏 / Alt-Tab / 桌面图标
- 单文件 exe(PyInstaller),无第三方依赖
- 跨屏位置记忆,1.75x / 2.0x 高 DPI 屏支持

### 安装使用

1. 下载下方 PlanMonitor.exe
2. 双击运行,首次会提示填入 AK / SK
3. AK / SK 在 火山引擎控制台 -> 访问控制 -> API 访问密钥 创建

### 安全

- 凭证只存在本地 config.json,不上传任何第三方
- 所有 API 请求直接发到火山方舟官方域名 ark.cn-beijing.volcengineapi.com

### 性能

- 运行内存:8 MB
- 冷启动:< 1 秒
- exe 体积:41 MB(含 Qt 运行库)
