# OKX 山寨币扫描器 V3 - 网页版

专为手机浏览器优化的版本，可直接在 iPhone Safari / Chrome 中使用。

## 功能亮点

- 手机友好界面（Streamlit）
- 侧边栏可调参数
- 实时进度条
- 按颈线状态筛选
- 图表内嵌显示（含止损 / 1.5R / 2R / 颈线）
- 结构增加最小波幅过滤，减少假信号
- 只读行情，不需要 API Key，不会下单

## 本地运行（推荐先测试）

```bash
# 进入目录
cd okx_altcoin_scanner_v3

# 安装依赖
pip install -r requirements.txt

# 启动网页
streamlit run app.py
```

启动后浏览器会自动打开 `http://localhost:8501`。

### 让手机也能访问（同一 Wi-Fi）

1. 电脑启动时加上：
   ```bash
   streamlit run app.py --server.address 0.0.0.0
   ```
2. 查看电脑局域网 IP（例如 `192.168.1.23`）
3. 手机浏览器打开：`http://192.168.1.23:8501`

## 部署到公网（推荐长期使用）

可部署到以下免费/低成本平台，之后手机随时打开链接即可：

| 平台 | 说明 |
|------|------|
| **Streamlit Community Cloud** | 免费，最简单，绑定 GitHub 即可 |
| Railway / Render / Fly.io | 免费额度足够日常使用 |
| 自己的 VPS | 最稳定 |

### Streamlit Community Cloud 快速部署步骤

1. 把本文件夹推到 GitHub 仓库
2. 打开 https://share.streamlit.io
3. 用 GitHub 登录 → New app → 选择仓库和 `app.py`
4. 部署完成后会得到一个 `https://xxxx.streamlit.app` 链接
5. 把这个链接加到 iPhone 主屏幕即可当 App 用

## 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 最小/最大成交额 | 1000万–3000万 | 过滤成交额区间 |
| 金叉新鲜度 | 2 | 最近几根已收盘K线内发生金叉 |
| 止损 ATR 缓冲 | 0.3 | 止损 = L2 - 0.3×ATR |
| 最大止损距离% | 5% | 超过则剔除 |
| 结构最小波幅% | 1.5% | L1→H1 和 L2→H2 的最小涨幅 |
| 并发数 | 3 | 遇 API 限频可降低 |

## 重要提示

1. 结果仅为研究信号，不构成交易建议。
2. 止损/止盈为参考价，实际会受滑点、手续费、资金费率影响。
3. 结构识别是按更高低点+更高高点规则实现的，建议结合图表人工确认。
4. 公开接口有频率限制，高峰时段建议把并发降到 2–3。

## 文件结构

```
okx_altcoin_scanner_v3/
├── app.py              # 网页入口
├── scanner_core.py     # 扫描核心逻辑
├── requirements.txt
└── README.md
```
