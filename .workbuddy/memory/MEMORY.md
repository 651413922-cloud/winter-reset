# 长期记忆

## 项目: VPN行为分析工具 (winter-reset)

### 架构
- `apiwireshark.py`: 网络层抓包分析 (基于 tshark CLI, 不使用 pyshark)
  - v2.0: 状态机驱动 + 滑动窗口 + 加权置信度 + 4种VPN行为事件识别
- `vpn_automation/`: UI层自动化 (图像匹配 + OCR, 控制VPN客户端)

### 技术栈
- Python 3.12.10
- tshark (Wireshark CLI) 实时抓包
- 状态机驱动的行为识别

### Windows subprocess 编码约定
- **永远不要在 Windows 下对 tshark subprocess 使用 `text=True`**
- 必须使用 `text=False` + 手动 `.decode("utf-8", errors="replace")`
- 否则 GBK 无法解码 tshark 的 UTF-8 中文输出

### 关键约定
- 所有模块内嵌在单个文件中，不新建额外模块文件
- 只分析元数据 (DNS / TLS SNI / IP), 不解密内容
- 输出JSONL格式的事件日志

### 用户偏好
- 使用腾讯文档表格做问题追踪
- 渐进式交互: 先发起初始请求，通过后续追问逐步调整
