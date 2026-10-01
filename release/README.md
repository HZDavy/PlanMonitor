# Coding Plan 监控助手

> 一个常驻桌面角落的小工具,实时显示你在火山方舟 Coding Plan / Agent Plan 的剩余用量。

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![PyQt5](https://img.shields.io/badge/PyQt5-5.15%2B-green)](https://pypi.org/project/PyQt5/)
[![License](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)
[![Release](https://img.shields.io/github/v/release/USER/coding-plan-monitor)](../../releases)

![screenshot](docs/preview.png)

## 这是什么

Coding Plan 个人版通常按"近 5 小时 / 近 1 周 / 近 1 月"三个滚动窗口算用量,官方控制台刷新比较慢,点开才知道用了多少。

这个工具做了 3 件事:

1. **常驻桌面浮窗**(默认右下角,可拖动,可置顶)
2. **每 30 秒自动拉一次** GetCodingPlanUsage API
3. **大字号显示**当前用量百分比 + 距下次重置的倒计时

整个进程占用 **8 MB 内存**,启动到完全显示 < 1 秒。

## 下载使用 (普通用户)

直接去 [Releases](../../releases) 页面下载最新版本的 `CodingPlanMonitor.exe`,双击运行即可。

> 首次运行会弹窗让你填火山方舟的 Access Key 和 Secret Key。本工具**不会**把这两个 key 上传到任何第三方服务器,只用来直接调用火山方舟官方 API。

## 自己编译 (开发者)

需要 Python 3.10+,PyQt5,PyInstaller,requests:

```bash
git clone https://github.com/USER/coding-plan-monitor.git
cd coding-plan-monitor
pip install PyQt5 requests pyinstaller
pyinstaller CodingPlanMonitor.spec --noconfirm
```

生成的可执行文件在 `dist/CodingPlanMonitor.exe`。

## 配置

程序首次运行会在 exe 同目录生成 `config.json`,内容如下:

```json
{
  "ak": "<YOUR_ACCESS_KEY>",
  "sk": "<YOUR_SECRET_KEY>",
  "always_on_top": true,
  "screen_index": -1,
  "geometry": {"x": 60, "y": 60}
}
```

| 字段 | 说明 |
|---|---|
| `ak` / `sk` | 火山方舟 IAM 凭证,在控制台 → 访问控制 → API 访问密钥 创建 |
| `always_on_top` | 窗口是否置顶 |
| `screen_index` | 上次所在的屏幕索引(多屏场景用) |
| `geometry` | 窗口位置(下次启动恢复) |

**重要:此文件含你的私钥,请勿提交到任何公开仓库。本仓已通过 `.gitignore` 屏蔽。**

## 界面

* **顶部**: 火山方舟 logo + "已连接" 状态(绿灯)
* **三张卡片**:
  * 近 5 小时用量 + 距重置
  * 近一周用量 + 距重置
  * 近一月用量 + 距重置
* **右上角 ≡**: 弹出菜单(刷新 / 置顶 / 移动到副屏 / 设置 AK / 退出)
* **系统托盘**: 关闭窗口后常驻托盘,右键唤出菜单

## 技术栈

* **Python 3.10+** — 无任何 C/C++ 扩展依赖,纯 Python
* **PyQt5** — UI 框架(只用了 QtWidgets + QtCore + QtGui + QtSvg,无 WebEngine)
* **requests** — HTTP 客户端
* **PyInstaller** — 单文件打包
* **HTML + CSS + JS** — 官网(本仓 `docs/index.html`,GitHub Pages 自动托管)

## 体积

打包后 `CodingPlanMonitor.exe` 约 **42 MB**,运行内存 **7-8 MB**。

> 大体积全部来自 PyQt5 自带的 Qt 运行库(launcher + GUI 引擎),本身程序代码 < 100 KB。

## 跨屏 / 多 DPI

* 窗口**宽度固定不可拉伸**(`setMinimumSize` = `setMaximumSize`)
* 启动时按 cfg 中的屏幕索引恢复位置
* 拖动时锁高度,避免被 OS 自动拉伸

## 安全 / 隐私

* 不收集任何数据
* 不联网(除官方 API 调用外)
* 代码完全开源,欢迎审查

## 路线图

* [x] 三种时间窗(5h / 1w / 1mo)用量显示
* [x] 倒计时到下次重置
* [x] 桌面浮窗 + 置顶
* [x] 系统托盘
* [ ] 主题切换(深 / 浅)
* [ ] 自定义刷新频率
* [ ] 用量预警(超过 80% 提醒)

## 贡献

PR 欢迎,提 issue 也欢迎。

## License

MIT — 见 [LICENSE](LICENSE)