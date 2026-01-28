"""
破底翻（C型）事件偵測器模組
Detection of C-type pattern: Consolidation -> Breakdown -> Reclaim
"""
import pandas as pd
import numpy as np
from .logger import get_logger

logger = get_logger(__name__)


def compute_atr(df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    """
    計算 True Range 和 ATR (Average True Range)

    Args:
        df: 包含 High, Low, Close 欄位的 DataFrame（需先按日期排序）
        n: ATR 週期（預設 14）

    Returns:
        DataFrame: 原始 df 加上 TR 和 ATR14 欄位
    """
    df = df.copy()

    # 計算 True Range
    # TR = max(High - Low, |High - Close_prev|, |Low - Close_prev|)
    df['prev_close'] = df['Close'].shift(1)

    df['tr1'] = df['High'] - df['Low']
    df['tr2'] = (df['High'] - df['prev_close']).abs()
    df['tr3'] = (df['Low'] - df['prev_close']).abs()

    df['TR'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)

    # 計算 ATR
    df[f'ATR{n}'] = df['TR'].rolling(window=n, min_periods=n).mean()

    # 清理臨時欄位
    df = df.drop(columns=['prev_close', 'tr1', 'tr2', 'tr3'])

    return df


def detect_consolidation(
    df: pd.DataFrame,
    window: int = 20,
    range_pct: float = 0.08,
    atr_pct: float = 0.025
) -> pd.DataFrame:
    """
    偵測多日盤整狀態

    盤整定義：
    1. box_range_pct = (box_high - box_low) / Close < range_pct (預設 8%)
    2. ATR14 / Close < atr_pct (預設 2.5%)

    Args:
        df: 包含 High, Low, Close, ATR14 欄位的 DataFrame
        window: rolling window 大小（預設 20）
        range_pct: 箱型區間佔比上限（預設 0.08）
        atr_pct: ATR 佔比上限（預設 0.025）

    Returns:
        DataFrame: 原始 df 加上 box_high, box_low, box_range_pct, is_consolidating 欄位
    """
    df = df.copy()

    # 計算 rolling 箱型高低點
    df['box_high'] = df['High'].rolling(window=window, min_periods=window).max()
    df['box_low'] = df['Low'].rolling(window=window, min_periods=window).min()

    # 計算箱型區間佔比
    df['box_range_pct'] = (df['box_high'] - df['box_low']) / df['Close']

    # 計算 ATR 佔比
    df['atr_pct'] = df['ATR14'] / df['Close']

    # 判斷是否為盤整
    df['is_consolidating'] = (
        (df['box_range_pct'] < range_pct) &
        (df['atr_pct'] < atr_pct)
    )

    return df


def detect_breakdown(df: pd.DataFrame, k_atr: float = 0.5) -> pd.DataFrame:
    """
    偵測假跌破事件（breakdown day）

    在盤整期間，若當日最低價跌破箱底參考值：
    Low < box_low_ref - k_atr * ATR14

    ⚠️ 避免 look-ahead bias：box_low_ref 使用前一日的 box_low

    Args:
        df: 包含 Low, box_low, ATR14, is_consolidating 欄位的 DataFrame
        k_atr: ATR 倍數（預設 0.5）

    Returns:
        DataFrame: 原始 df 加上 box_low_ref, breakdown_event 欄位
    """
    df = df.copy()

    # 使用前一日的 box_low 作為參考（避免 look-ahead）
    df['box_low_ref'] = df['box_low'].shift(1)

    # 計算跌破閾值
    df['breakdown_threshold'] = df['box_low_ref'] - k_atr * df['ATR14']

    # 判斷是否發生跌破：需要在盤整期間 且 最低價低於閾值
    df['breakdown_event'] = (
        df['is_consolidating'] &
        (df['Low'] < df['breakdown_threshold'])
    )

    return df


def detect_reclaim(df: pd.DataFrame, max_lag: int = 2) -> pd.DataFrame:
    """
    偵測收回箱底事件（reclaim）

    對每個 breakdown 日，檢查未來 1~max_lag 天內是否有首次收回箱底：
    Close > box_low_ref_at_breakdown

    ⚠️ 此函數需在完整歷史資料上執行，但標記邏輯符合時序性

    Args:
        df: 包含 Close, box_low_ref, breakdown_event 欄位的 DataFrame
        max_lag: 檢查未來最多幾天（預設 2）

    Returns:
        DataFrame: 原始 df 加上 reclaim_event, reclaim_lag 欄位
    """
    df = df.copy()
    df = df.reset_index(drop=True)

    # 初始化欄位
    df['reclaim_event'] = False
    df['reclaim_lag'] = np.nan
    df['breakdown_day_index'] = np.nan  # 記錄這筆 reclaim 對應到哪個 breakdown

    # 找出所有 breakdown 的索引
    breakdown_indices = df[df['breakdown_event']].index.tolist()

    logger.info(f"找到 {len(breakdown_indices)} 個 breakdown 事件")

    for bd_idx in breakdown_indices:
        # 取得 breakdown 當日的 box_low_ref
        box_low_ref_at_bd = df.loc[bd_idx, 'box_low_ref']

        if pd.isna(box_low_ref_at_bd):
            continue

        # 檢查未來 1 到 max_lag 天
        for lag in range(1, max_lag + 1):
            future_idx = bd_idx + lag

            # 確保索引在範圍內
            if future_idx >= len(df):
                break

            # 檢查是否收回箱底
            if df.loc[future_idx, 'Close'] > box_low_ref_at_bd:
                # 標記首次收回
                df.loc[future_idx, 'reclaim_event'] = True
                df.loc[future_idx, 'reclaim_lag'] = lag
                df.loc[future_idx, 'breakdown_day_index'] = bd_idx
                logger.debug(f"索引 {bd_idx} 的 breakdown 在 {lag} 天後（索引 {future_idx}）收回")
                break  # 只標記首次收回

    return df


def detect_c_pattern(
    df: pd.DataFrame,
    atr_period: int = 14,
    consolidation_window: int = 20,
    consolidation_range_pct: float = 0.08,
    consolidation_atr_pct: float = 0.025,
    breakdown_k_atr: float = 0.5,
    reclaim_max_lag: int = 2
) -> pd.DataFrame:
    """
    完整的破底翻（C型）事件偵測流程

    流程：
    1. 計算 ATR
    2. 偵測盤整
    3. 偵測假跌破
    4. 偵測收回箱底

    Args:
        df: 原始 OHLCV DataFrame（需包含 Open, High, Low, Close, Volume 欄位）
        atr_period: ATR 週期
        consolidation_window: 盤整判斷的 rolling window
        consolidation_range_pct: 盤整區間佔比上限
        consolidation_atr_pct: ATR 佔比上限
        breakdown_k_atr: 跌破閾值的 ATR 倍數
        reclaim_max_lag: 收回檢查的最大天數

    Returns:
        DataFrame: 包含所有偵測結果的 DataFrame
    """
    # 確保欄位名稱統一（首字母大寫）
    df = df.copy()
    df = df.rename(columns={
        'open': 'Open',
        'high': 'High',
        'low': 'Low',
        'close': 'Close',
        'volume': 'Volume'
    })

    # 確保按日期排序
    df = df.sort_values('date').reset_index(drop=True)

    logger.info("Step 1: 計算 ATR")
    df = compute_atr(df, n=atr_period)

    logger.info("Step 2: 偵測盤整")
    df = detect_consolidation(
        df,
        window=consolidation_window,
        range_pct=consolidation_range_pct,
        atr_pct=consolidation_atr_pct
    )

    logger.info("Step 3: 偵測假跌破")
    df = detect_breakdown(df, k_atr=breakdown_k_atr)

    logger.info("Step 4: 偵測收回箱底")
    df = detect_reclaim(df, max_lag=reclaim_max_lag)

    return df


def summarize_c_pattern_events(df: pd.DataFrame) -> pd.DataFrame:
    """
    彙整破底翻事件清單

    Args:
        df: 經過 detect_c_pattern 處理的 DataFrame

    Returns:
        DataFrame: 事件清單，包含：
            - date: 收回日期
            - code: 股票代碼
            - breakdown_date: 跌破日期
            - reclaim_date: 收回日期
            - reclaim_lag: 收回延遲天數
            - close: 收回日收盤價
            - box_low_ref: 箱底參考價
    """
    # 篩選出有 reclaim_event 的資料
    reclaim_df = df[df['reclaim_event']].copy()

    if reclaim_df.empty:
        logger.info("未發現任何破底翻事件")
        return pd.DataFrame()

    # 構建事件清單
    events = []
    for idx, row in reclaim_df.iterrows():
        bd_idx = int(row['breakdown_day_index'])
        breakdown_date = df.loc[bd_idx, 'date']

        event = {
            'code': row.get('code', 'Unknown'),
            'breakdown_date': breakdown_date,
            'reclaim_date': row['date'],
            'reclaim_lag': int(row['reclaim_lag']),
            'close_at_reclaim': row['Close'],
            'box_low_ref': row['box_low_ref'],
            'reclaim_pct': ((row['Close'] - row['box_low_ref']) / row['box_low_ref'] * 100) if row['box_low_ref'] > 0 else np.nan
        }
        events.append(event)

    events_df = pd.DataFrame(events)
    logger.info(f"找到 {len(events_df)} 個破底翻事件")

    return events_df
