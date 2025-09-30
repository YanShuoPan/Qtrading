"""
視覺化模組 - 繪製股票 K 線圖
"""
import tempfile
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from .stock_codes import get_stock_name
from .config import DEBUG_MODE
from .logger import get_logger

logger = get_logger(__name__)


def plot_candlestick(ax, stock_data):
    """
    在指定的 ax 上繪製 K 棒圖

    Args:
        ax: matplotlib axes 對象
        stock_data: 股票數據 DataFrame
    """
    stock_data = stock_data.copy().reset_index(drop=True)

    for idx, row in stock_data.iterrows():
        date_num = idx
        open_price = row['open']
        high_price = row['high']
        low_price = row['low']
        close_price = row['close']

        color = '#FF4444' if close_price >= open_price else '#00AA00'

        # 繪製上下影線
        ax.plot([date_num, date_num], [low_price, high_price], color=color, linewidth=0.8)

        # 繪製 K 棒實體
        body_height = abs(close_price - open_price)
        body_bottom = min(open_price, close_price)
        ax.bar(date_num, body_height, bottom=body_bottom, color=color, width=0.6, alpha=0.8)


def plot_stock_charts(codes: list, prices: pd.DataFrame) -> str:
    """
    繪製最多 6 支股票的 K 棒圖（2x3 子圖）

    Args:
        codes: 股票代碼列表
        prices: 股價數據 DataFrame

    Returns:
        str: 圖表檔案路徑
    """
    logger.debug(f'開始繪製圖表，股票代碼: {codes}')
    codes = codes[:6]
    n_stocks = len(codes)
    if n_stocks == 0:
        logger.warning("沒有股票代碼需要繪製")
        return None

    # 設定字體優先級：Windows字體 -> Linux字體 -> 通用字體
    fonts = ['Microsoft JhengHei', 'SimHei', 'WenQuanYi Zen Hei', 'WenQuanYi Micro Hei', 'DejaVu Sans', 'Arial']
    plt.rcParams['font.sans-serif'] = fonts
    plt.rcParams['axes.unicode_minus'] = False

    # 在 CI 環境中清除字體快取以確保使用新安裝的字體
    import os
    if os.environ.get('CI') or os.environ.get('GITHUB_ACTIONS'):
        try:
            import matplotlib.font_manager
            matplotlib.font_manager._load_fontmanager(try_read_cache=False)
            logger.debug("CI 環境：已重新載入字體管理器")
        except Exception as e:
            logger.warning(f"重新載入字體管理器失敗: {e}")

    if DEBUG_MODE:
        logger.debug(f"matplotlib 後端: {matplotlib.get_backend()}")
        logger.debug(f"設定字體順序: {fonts}")

    fig, axes = plt.subplots(2, 3, figsize=(18, 12))
    axes = axes.flatten()

    for i, code in enumerate(codes):
        stock_data = prices[prices["code"] == code].sort_values("date").tail(90)

        if stock_data.empty or len(stock_data) < 20:
            stock_name = get_stock_name(code)
            axes[i].text(0.5, 0.5, f"{code} {stock_name}\n數據不足",
                        ha='center', va='center', fontsize=14)
            axes[i].set_xticks([])
            axes[i].set_yticks([])
            continue

        stock_data = stock_data.copy()
        stock_data["ma20"] = stock_data["close"].rolling(20, min_periods=20).mean()

        ax = axes[i]
        plot_candlestick(ax, stock_data)

        # 繪製 MA20
        valid_ma20 = stock_data[stock_data["ma20"].notna()]
        if not valid_ma20.empty:
            ma20_indices = valid_ma20.index - stock_data.index[0]
            ax.plot(ma20_indices, valid_ma20["ma20"], label="MA20",
                   linewidth=2, linestyle="--", alpha=0.7, color='#2E86DE')

        stock_name = get_stock_name(code)
        ax.set_title(f"{code} {stock_name}", fontsize=14, fontweight='bold', pad=10)
        ax.legend(fontsize=9, loc='upper left')
        ax.grid(True, alpha=0.3, linestyle='--')

        # 設定 X 軸日期標籤
        date_labels = stock_data["date"].dt.strftime('%m/%d').tolist()
        step = max(1, len(date_labels) // 6)
        tick_positions = list(range(0, len(date_labels), step))
        tick_labels = [date_labels[i] for i in tick_positions]
        ax.set_xticks(tick_positions)
        ax.set_xticklabels(tick_labels, rotation=45, fontsize=9)
        ax.tick_params(axis='y', labelsize=9)

    # 移除多餘的子圖
    for i in range(n_stocks, 6):
        fig.delaxes(axes[i])

    plt.tight_layout()

    # 儲存圖表到暫存檔案
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    plt.savefig(temp_file.name, dpi=100, bbox_inches='tight')
    plt.close()

    logger.info(f"✅ 圖表已生成: {temp_file.name}")
    return temp_file.name