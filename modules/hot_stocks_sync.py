"""
熱門題材股同步模組 - 從 TW_stock_tagging_system 讀取每日熱門股清單
"""
import os
import re
import logging

import pandas as pd

from .stock_codes import STOCK_NAMES

logger = logging.getLogger(__name__)


def load_hot_stocks(csv_path: str | None = None) -> dict[str, dict]:
    """
    從 hot_stocks.csv 讀取當日熱門股資訊。

    CSV 格式（exports/hot_stocks.csv）：
        rank, tag_id, tag_name, tag_type, mention_count, stock_count, stocks, snapshot_date
        stocks 欄位格式：名稱(代碼)、名稱(代碼)

    回傳：
        {stock_code: {"tag_name": str, "mention_count": int, "rank": int}}
        若同一股票出現在多個題材，保留 mention_count 最高的題材。
    """
    if csv_path is None:
        from .config import HOT_STOCKS_CSV_PATH
        csv_path = HOT_STOCKS_CSV_PATH

    if not csv_path or not os.path.exists(csv_path):
        logger.warning(f"hot_stocks.csv 不存在或未設定路徑: {csv_path}")
        return {}

    try:
        df = pd.read_csv(csv_path, encoding="utf-8-sig")
    except Exception as e:
        logger.error(f"讀取 hot_stocks.csv 失敗: {e}")
        return {}

    required_cols = {"stocks", "tag_name", "mention_count", "rank"}
    if not required_cols.issubset(df.columns):
        logger.error(f"hot_stocks.csv 缺少必要欄位: {required_cols - set(df.columns)}")
        return {}

    result: dict[str, dict] = {}
    for _, row in df.iterrows():
        stocks_str = str(row.get("stocks", ""))
        tag_name = str(row.get("tag_name", ""))
        mention_count = int(row.get("mention_count", 0))
        rank = int(row.get("rank", 99))

        # 從 "名稱(代碼)" 格式解析股票代碼
        codes = re.findall(r"\((\d+)\)", stocks_str)
        for code in codes:
            if code not in result or mention_count > result[code]["mention_count"]:
                result[code] = {
                    "tag_name": tag_name,
                    "mention_count": mention_count,
                    "rank": rank,
                }

    logger.info(f"載入熱門題材股：{len(result)} 支（來源：{csv_path}）")
    return result


def get_hot_codes_list(csv_path: str | None = None) -> list[str]:
    """回傳熱門股代碼列表。"""
    return list(load_hot_stocks(csv_path).keys())


def build_hot_stocks_df(
    hot_stocks: dict[str, dict],
    hist: pd.DataFrame,
    max_per_tag: int = 6,
) -> pd.DataFrame:
    """
    建立熱門股 DataFrame（只保留 hist 中有價格資料的股票）。
    每個主題只取交易量能最大的前 max_per_tag 支（量 × 收盤價）。

    Args:
        hot_stocks:   load_hot_stocks() 的回傳值
        hist:         Qtrading 歷史股價 DataFrame
        max_per_tag:  每個主題最多保留幾支（預設 6）

    Returns:
        DataFrame with columns: code, tag_name, mention_count, rank, trading_value
    """
    if not hot_stocks or hist.empty:
        return pd.DataFrame()

    # 取每支股票最新一日的交易量能
    latest = (
        hist.sort_values("date")
        .groupby("code")
        .tail(1)
        .assign(trading_value=lambda d: d["close"] * d["volume"])
        .set_index("code")["trading_value"]
    )

    # 只保留資料量足夠的股票（>= 30 筆，MA20 需要至少 20 筆）
    code_counts = hist.groupby("code").size()
    available_codes = set(code_counts[code_counts >= 30].index)

    rows = []
    for code, info in hot_stocks.items():
        if code in available_codes and code in STOCK_NAMES:
            rows.append({
                "code": code,
                "tag_name": info["tag_name"],
                "mention_count": info["mention_count"],
                "rank": info["rank"],
                "trading_value": latest.get(code, 0),
            })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # 每個主題只保留交易量能最大的前 max_per_tag 支
    df = (
        df.sort_values("trading_value", ascending=False)
        .groupby("tag_name", sort=False)
        .head(max_per_tag)
        .sort_values(["rank", "trading_value"], ascending=[True, False])
        .reset_index(drop=True)
    )

    logger.info(
        f"熱門股篩選後：{len(df)} 支"
        f"（每主題最多 {max_per_tag} 支，依交易量能排序）"
    )
    return df


def load_stock_tags(
    stock_tag_map_path: str | None = None,
    tag_master_path: str | None = None,
    max_tags: int = 2,
) -> dict[str, list[str]]:
    """
    從 stock_tag_map.csv + tag_master.csv 建立股票標籤對照表。

    Returns:
        {股票代碼(str): [標籤中文名1, 標籤中文名2]}  (最多 max_tags 個，core 優先)
    """
    if stock_tag_map_path is None:
        from .config import STOCK_TAG_MAP_CSV
        stock_tag_map_path = STOCK_TAG_MAP_CSV
    if tag_master_path is None:
        from .config import TAG_MASTER_CSV
        tag_master_path = TAG_MASTER_CSV

    try:
        stm = pd.read_csv(stock_tag_map_path, encoding="utf-8-sig")
        tm = pd.read_csv(tag_master_path, encoding="utf-8-sig")
    except Exception as e:
        logger.warning(f"載入 stock_tags 失敗: {e}")
        return {}

    # tag_id → 中文名稱
    tag_name_map: dict[str, str] = dict(zip(tm["tag_id"], tm["tag_name"]))

    # core 優先排序
    score_order = {"core": 0, "related": 1}
    stm = stm.copy()
    stm["_sort"] = stm["score_level"].map(score_order).fillna(2)
    stm = stm.sort_values(["stock_id", "_sort"])

    result: dict[str, list[str]] = {}
    for _, row in stm.iterrows():
        code = str(int(row["stock_id"]))
        tag_name = tag_name_map.get(row["tag_id"], "")
        if not tag_name:
            continue
        tags = result.setdefault(code, [])
        if len(tags) < max_tags:
            tags.append(tag_name)

    logger.info(f"載入股票標籤：{len(result)} 支股票有標籤資料")
    return result
