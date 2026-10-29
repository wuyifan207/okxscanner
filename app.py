#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OKX 山寨币扫描器 V3 - 网页版（手机友好）
使用 Streamlit，可直接在 iPhone 浏览器中使用。
"""

import os
import time
from datetime import datetime

import streamlit as st
import pandas as pd

from scanner_core import run_scan

# 页面配置（手机友好）
st.set_page_config(
    page_title="OKX 山寨币扫描器",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 自定义一点样式，提升手机体验
st.markdown("""
<style>
    .stButton>button {
        width: 100%;
        height: 3em;
        font-size: 1.1em;
    }
    .block-container {
        padding-top: 1.2rem;
        padding-bottom: 2rem;
    }
    div[data-testid="stMetric"] {
        background-color: #1e1e1e;
        border-radius: 8px;
        padding: 8px 12px;
    }
</style>
""", unsafe_allow_html=True)

st.title("📈 OKX 山寨币扫描器 V3")
st.caption("只读行情 · 不下单 · 专为手机浏览器优化")

# ========== 侧边栏参数 ==========
with st.sidebar:
    st.header("扫描参数")
    min_turnover = st.number_input("最小成交额 (USDT)", value=10_000_000, step=1_000_000, format="%d")
    max_turnover = st.number_input("最大成交额 (USDT)", value=30_000_000, step=1_000_000, format="%d")
    cross_lookback = st.slider("金叉新鲜度（最近几根已收盘K线）", 1, 5, 2)
    atr_buffer = st.slider("止损 ATR 缓冲", 0.1, 1.0, 0.3, 0.1)
    max_stop_pct = st.slider("最大止损距离 %", 2.0, 10.0, 5.0, 0.5)
    min_amp_pct = st.slider("结构最小波幅 %", 0.8, 5.0, 1.5, 0.1)
    workers = st.slider("并发数（遇限频可降低）", 1, 6, 3)
    max_symbols = st.number_input("最多扫描合约数（0=全部）", value=0, min_value=0, step=5)

    st.markdown("---")
    st.markdown("**说明**")
    st.markdown("""
    - 成交额优先使用 OKX 官方计价币字段  
    - 只使用已收盘 K 线  
    - 结构要求更高低点 + 更高高点  
    - 结果仅供研究，非交易建议  
    """)

# ========== 主界面 ==========
col1, col2 = st.columns([3, 1])
with col1:
    st.markdown("点击下方按钮开始扫描（通常需要 1~3 分钟）")
with col2:
    run_btn = st.button("🚀 开始扫描", type="primary")

# 输出目录
OUTPUT_DIR = "scan_output_web"
os.makedirs(OUTPUT_DIR, exist_ok=True)

if run_btn:
    args = {
        "min_turnover": float(min_turnover),
        "max_turnover": float(max_turnover),
        "cross_lookback": int(cross_lookback),
        "atr_buffer": float(atr_buffer),
        "max_stop_pct": float(max_stop_pct),
        "min_swing_bars": 3,
        "max_swing_bars": 45,
        "min_amp_pct": float(min_amp_pct),
        "workers": int(workers),
        "max_symbols": int(max_symbols) if max_symbols > 0 else 0,
        "output": OUTPUT_DIR
    }

    progress_bar = st.progress(0)
    status_text = st.empty()
    hit_text = st.empty()

    def progress_callback(done, total, hits):
        progress_bar.progress(min(done / total, 1.0))
        status_text.text(f"进度：{done}/{total}")
        hit_text.text(f"当前命中：{hits}")

    with st.spinner("正在获取合约列表并扫描……"):
        start_time = time.time()
        results, errors = run_scan(args, progress_callback=progress_callback)
        elapsed = time.time() - start_time

    progress_bar.progress(1.0)
    status_text.text(f"扫描完成，耗时 {elapsed:.1f} 秒")
    hit_text.empty()

    # 保存结果到 session，方便刷新后还能看
    st.session_state["last_results"] = results
    st.session_state["last_errors"] = errors
    st.session_state["last_args"] = args
    st.session_state["scan_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# 显示结果
results = st.session_state.get("last_results", [])
errors = st.session_state.get("last_errors", [])
scan_time = st.session_state.get("scan_time", "")

if results:
    st.success(f"扫描完成 · {scan_time} · 共命中 **{len(results)}** 个候选")

    # 快速统计
    c1, c2, c3, c4 = st.columns(4)
    broken = sum(1 for r in results if r["neckline_status"] == "已突破颈线")
    near = sum(1 for r in results if r["neckline_status"] == "接近颈线")
    waiting = sum(1 for r in results if r["neckline_status"] == "尚未到颈线")
    c1.metric("已突破颈线", broken)
    c2.metric("接近颈线", near)
    c3.metric("等待确认", waiting)
    c4.metric("总候选", len(results))

    # 筛选
    st.subheader("筛选结果")
    filter_status = st.multiselect(
        "按颈线状态筛选",
        options=["已突破颈线", "接近颈线", "尚未到颈线"],
        default=["已突破颈线", "接近颈线"]
    )
    only_volume = st.checkbox("仅显示 15m 成交量放大的", value=False)

    filtered = [
        r for r in results
        if r["neckline_status"] in filter_status
        and (not only_volume or r.get("volume_above_20bar_avg_15m", False))
    ]

    if not filtered:
        st.warning("当前筛选条件下没有结果，请放宽筛选。")
    else:
        # 表格
        df = pd.DataFrame(filtered)
        show_cols = [
            "instId", "turnover24h_USDT", "signal_status", "neckline_status",
            "last_price", "stop_distance_pct", "stop_loss_reference",
            "TP_1_5R_reference", "TP_2R_reference", "signal"
        ]
        display_df = df[show_cols].copy()
        display_df["turnover24h_USDT"] = display_df["turnover24h_USDT"].apply(lambda x: f"{x/1e6:.1f}M")
        display_df = display_df.rename(columns={
            "instId": "合约",
            "turnover24h_USDT": "成交额",
            "signal_status": "状态",
            "neckline_status": "颈线",
            "last_price": "最新价",
            "stop_distance_pct": "止损距离%",
            "stop_loss_reference": "参考止损",
            "TP_1_5R_reference": "1.5R",
            "TP_2R_reference": "2R",
            "signal": "信号"
        })
        st.dataframe(display_df, use_container_width=True, hide_index=True)

        # 图表展示
        st.subheader("K线图表")
        for r in filtered:
            with st.expander(f"{r['instId']}  ·  {r['neckline_status']}  ·  止损距离 {r['stop_distance_pct']}%", expanded=False):
                st.markdown(f"""
                **信号**：{r['signal']}  
                **最新价**：{r['last_price']:.6g}  
                **参考止损**：{r['stop_loss_reference']:.6g}（距离 {r['stop_distance_pct']}%）  
                **1.5R**：{r['TP_1_5R_reference']:.6g} **2R**：{r['TP_2R_reference']:.6g}  
                **成交额来源**：{r['turnover_source']}  
                **15m 量能放大**：{"是" if r.get("volume_above_20bar_avg_15m") else "否"}
                """)
                if os.path.exists(r["chart"]):
                    st.image(r["chart"], use_container_width=True)
                else:
                    st.info("图表文件不存在")

elif "last_results" in st.session_state:
    st.info("本轮没有币种同时满足全部条件。可以尝试放宽成交额范围或金叉新鲜度。")

if errors:
    with st.expander(f"接口错误（{len(errors)} 个）"):
        for e in errors:
            st.text(f"{e.get('_error')}: {e.get('error')}")

st.markdown("---")
st.caption("本工具仅获取公开行情数据，不会下单。结果仅供研究参考，请自行判断风险。")
