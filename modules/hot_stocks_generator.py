"""
每日熱門股生成模組

整合三個新聞來源，在 Qtrading 內自行產生 hot_stocks.csv：
  1. Google News RSS（依主題關鍵字查詢）
  2. PTT 股版（抓最新 5 頁標題，做關鍵字比對）
  3. 鉅亨網 Anue（API，含直接股票代碼標記）

計分方式：
  - 各來源的標題若包含某主題的 news_keywords，該主題 +1
  - Anue 每篇文章若其 stocks 欄位含有屬於某主題的股票，該主題額外 +1
"""

import os
import time
import logging
from collections import defaultdict
from datetime import datetime
from urllib.parse import quote

import feedparser
import pandas as pd
import requests
import yaml
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

RSS_BASE_URL = "https://news.google.com/rss/search"

PTT_BASE_URL = "https://www.ptt.cc"
PTT_STOCK_URL = f"{PTT_BASE_URL}/bbs/Stock/index.html"
PTT_COOKIES = {"over18": "1"}
PTT_SKIP_TAGS = {"[公告]", "[Announce]", "[版規]", "[活動]"}
# 這兩類文章有實質股票討論，需要抓內文
PTT_CONTENT_TAGS = {"[標的]", "[情報]"}

ANUE_API_BASE = "https://api.cnyes.com/media/api/v1/newslist/category"
ANUE_CATEGORIES = ["tw_stock", "tw_stock_news", "headline"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


# ─── 資料載入 ──────────────────────────────────────────────────────────────

def _load_theme_keywords(yaml_path: str) -> dict[str, dict]:
    """
    載入 theme_keywords.yaml。
    回傳 {tag_id: {"tag_type": str, "news_keywords": [str]}}
    """
    if not os.path.exists(yaml_path):
        logger.error(f"theme_keywords.yaml 不存在: {yaml_path}")
        return {}

    with open(yaml_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    result = {}
    for tag_id, cfg in raw.items():
        kws = cfg.get("news_keywords", [])
        if not kws:
            continue
        result[tag_id] = {
            "tag_type": cfg.get("tag_type", "theme"),
            "news_keywords": [str(k) for k in kws],
        }

    logger.info(f"載入 {len(result)} 個主題關鍵字設定")
    return result


def _load_stock_tag_map(csv_path: str) -> dict[str, set[str]]:
    """
    載入 stock_tag_map.csv。
    回傳 {tag_id: {stock_id, ...}}
    """
    if not os.path.exists(csv_path):
        logger.error(f"stock_tag_map.csv 不存在: {csv_path}")
        return {}

    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    result: dict[str, set[str]] = defaultdict(set)
    for _, row in df.iterrows():
        tag_id = str(row.get("tag_id", "")).strip()
        stock_id = str(row.get("stock_id", "")).strip()
        if tag_id and stock_id:
            result[tag_id].add(stock_id)

    logger.info(f"載入 {len(result)} 個主題的股票對應")
    return dict(result)


def _load_tag_names(csv_path: str) -> dict[str, str]:
    """
    載入 tag_master.csv，取得 {tag_id: tag_name}。
    若檔案不存在，回傳空 dict（後面會用 tag_id 代替）。
    """
    if not csv_path or not os.path.exists(csv_path):
        return {}

    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    result = {}
    for _, row in df.iterrows():
        tag_id = str(row.get("tag_id", "")).strip()
        tag_name = str(row.get("tag_name", "")).strip()
        if tag_id and tag_name:
            result[tag_id] = tag_name
    return result


# ─── Google News RSS 抓取 ──────────────────────────────────────────────────

def _fetch_rss_titles(
    theme_keywords: dict[str, dict],
    delay: float = 1.5,
    lookback_days: int = 7,
) -> list[str]:
    """
    對每個主題的第一個關鍵字查詢 Google News RSS，
    收集所有新聞標題（去重）並回傳。
    """
    queries: set[str] = set()
    for cfg in theme_keywords.values():
        kw = cfg["news_keywords"][0]
        queries.add(f"{kw} 台股")

    all_titles: list[str] = []
    seen: set[str] = set()
    total = len(queries)

    for i, query in enumerate(queries, 1):
        try:
            encoded = quote(query)
            url = (
                f"{RSS_BASE_URL}?q={encoded}"
                f"+when:{lookback_days}d&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
            )
            feed = feedparser.parse(url)
            for entry in feed.entries:
                title = entry.get("title", "")
                if title and title not in seen:
                    seen.add(title)
                    all_titles.append(title)
            logger.debug(f"RSS [{i}/{total}] {query!r} → {len(feed.entries)} 筆")
        except Exception as e:
            logger.warning(f"RSS 抓取失敗 {query!r}: {e}")
        time.sleep(delay)

    logger.info(f"Google News RSS：共 {len(all_titles)} 篇不重複標題")
    return all_titles


# ─── PTT 股版抓取 ──────────────────────────────────────────────────────────

def _fetch_ptt_article_content(
    session: requests.Session,
    url: str,
    max_chars: int = 1500,
) -> str:
    """抓取單篇 PTT 文章內文（去除 meta 區與推文）。"""
    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        main = soup.find("div", id="main-content")
        if not main:
            return ""
        for tag in main.select(
            "div.article-metaline, div.article-metaline-right, div.push"
        ):
            tag.decompose()
        text = main.get_text(separator="\n", strip=True)
        # 截斷 footer（-- 分隔線之後）
        if "\n--\n" in text:
            text = text[: text.index("\n--\n")]
        return text[:max_chars].strip()
    except Exception as e:
        logger.debug(f"PTT 內文抓取失敗 {url}: {e}")
        return ""


def _fetch_ptt_texts(pages: int = 5, delay: float = 1.5) -> list[str]:
    """
    抓取 PTT 股版文章，回傳「可供關鍵字比對的文字」列表：
      - 一般文章：只用標題
      - [標的] / [情報] 文章：標題 + 內文（這類文章才有實質股票分析）
    """
    texts: list[str] = []
    content_items: list[tuple[str, str]] = []  # (title, url)
    session = requests.Session()
    session.cookies.update(PTT_COOKIES)
    session.headers.update(HEADERS)
    current_url = PTT_STOCK_URL

    # 第一輪：抓所有頁面的標題
    for page_num in range(pages):
        try:
            resp = session.get(current_url, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")

            for div in soup.select("div.r-ent"):
                title_tag = div.select_one("div.title a")
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                if any(title.startswith(skip) for skip in PTT_SKIP_TAGS):
                    continue

                href = title_tag.get("href", "")
                # [標的] / [情報] 類另外記錄，稍後抓內文
                if any(title.startswith(tag) for tag in PTT_CONTENT_TAGS) and href:
                    content_items.append((title, PTT_BASE_URL + href))
                else:
                    texts.append(title)

            # 找「上一頁」連結
            prev_url = None
            for btn in soup.select("div.btn-group-paging a"):
                if "上頁" in btn.get_text():
                    prev_url = btn.get("href")
                    break
            if not prev_url:
                break
            current_url = PTT_BASE_URL + prev_url

        except Exception as e:
            logger.warning(f"PTT 抓取失敗 page {page_num + 1}: {e}")
            break

        time.sleep(delay)

    logger.info(
        f"PTT 股版：{len(texts)} 篇一般標題，{len(content_items)} 篇[標的]/[情報]待抓內文"
    )

    # 第二輪：對 [標的] / [情報] 抓內文，合併成「標題 + 內文」
    for title, url in content_items:
        content = _fetch_ptt_article_content(session, url)
        combined = f"{title}\n{content}" if content else title
        texts.append(combined)
        time.sleep(delay)

    logger.info(f"PTT 股版：共 {len(texts)} 筆文字（含 {len(content_items)} 篇內文）")
    return texts


# ─── 鉅亨網抓取 ──────────────────────────────────────────────────────────

def _fetch_anue_data(
    limit_per_category: int = 30,
    delay: float = 1.0,
) -> tuple[list[str], list[set[str]]]:
    """
    從鉅亨網 API 抓取台股新聞。
    回傳:
      - titles:     所有新聞標題（供關鍵字比對）
      - stock_sets: 每篇文章的台股代碼集合（供直接股票→主題計數）
    """
    titles: list[str] = []
    stock_sets: list[set[str]] = []
    seen_ids: set[int] = set()

    for category in ANUE_CATEGORIES:
        url = f"{ANUE_API_BASE}/{category}?limit={limit_per_category}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            news_list = data.get("items", {}).get("data", [])
            fetched = 0
            for raw in news_list:
                news_id = raw.get("newsId", 0)
                if news_id in seen_ids:
                    continue
                seen_ids.add(news_id)

                title = (raw.get("title") or "").strip()
                # 只保留台股代號（排除 US- 開頭）
                stocks = {
                    s for s in (raw.get("stock") or [])
                    if not s.startswith("US-")
                }
                titles.append(title)
                stock_sets.append(stocks)
                fetched += 1

            logger.debug(f"Anue [{category}]: {fetched} 筆")

        except Exception as e:
            logger.warning(f"Anue 抓取失敗 [{category}]: {e}")

        time.sleep(delay)

    logger.info(f"鉅亨網：共 {len(titles)} 篇新聞")
    return titles, stock_sets


# ─── 計分 ──────────────────────────────────────────────────────────────────

def _count_keyword_mentions(
    titles: list[str],
    theme_keywords: dict[str, dict],
) -> dict[str, int]:
    """
    對標題列表做關鍵字比對，統計每個 tag_id 被提及幾次。
    每篇標題若含任一 news_keyword 就算 +1。
    """
    counts: dict[str, int] = defaultdict(int)
    for tag_id, cfg in theme_keywords.items():
        kws = cfg["news_keywords"]
        count = sum(
            1 for title in titles
            if any(kw.lower() in title.lower() for kw in kws)
        )
        if count > 0:
            counts[tag_id] = count
    return dict(counts)


def _count_anue_stock_mentions(
    stock_sets: list[set[str]],
    stock_tag_map: dict[str, set[str]],
) -> dict[str, int]:
    """
    利用 Anue 直接標記的股票代碼，反查 tag_id 計數。
    每篇文章若含有屬於某主題的股票，該主題 +1（每篇最多 +1）。
    """
    # 建立反查表: stock_id → [tag_ids]
    stock_to_tags: dict[str, list[str]] = defaultdict(list)
    for tag_id, stocks in stock_tag_map.items():
        for sid in stocks:
            stock_to_tags[sid].append(tag_id)

    counts: dict[str, int] = defaultdict(int)
    for stocks in stock_sets:
        hit_tags: set[str] = set()
        for sid in stocks:
            for tag_id in stock_to_tags.get(sid, []):
                hit_tags.add(tag_id)
        for tag_id in hit_tags:
            counts[tag_id] += 1

    return dict(counts)


# ─── 主要生成函式 ──────────────────────────────────────────────────────────

def generate_hot_stocks_csv(
    output_path: str | None = None,
    theme_keywords_path: str | None = None,
    stock_tag_map_path: str | None = None,
    tag_master_path: str | None = None,
    top_k: int = 10,
    rss_delay: float = 1.5,
    lookback_days: int = 7,
    ptt_pages: int = 5,
    ptt_delay: float = 1.5,
    anue_limit: int = 30,
    anue_delay: float = 1.0,
) -> bool:
    """
    整合 Google News RSS、PTT 股版、鉅亨網，生成每日 hot_stocks.csv。

    Returns:
        True = 成功，False = 失敗
    """
    from .config import (
        HOT_STOCKS_CSV_PATH,
        THEME_KEYWORDS_YAML,
        STOCK_TAG_MAP_CSV,
        TAG_MASTER_CSV,
    )
    from .stock_codes import STOCK_NAMES

    output_path = output_path or HOT_STOCKS_CSV_PATH
    theme_keywords_path = theme_keywords_path or THEME_KEYWORDS_YAML
    stock_tag_map_path = stock_tag_map_path or STOCK_TAG_MAP_CSV
    tag_master_path = tag_master_path or TAG_MASTER_CSV

    logger.info("=== 開始生成每日熱門股 ===")

    # 1. 載入設定
    theme_keywords = _load_theme_keywords(theme_keywords_path)
    stock_tag_map = _load_stock_tag_map(stock_tag_map_path)
    tag_names = _load_tag_names(tag_master_path)

    if not theme_keywords:
        logger.error("無法載入主題關鍵字，停止生成")
        return False
    if not stock_tag_map:
        logger.error("無法載入股票-主題對應，停止生成")
        return False

    # 2. 抓取三個來源
    logger.info("--- [1/3] Google News RSS ---")
    rss_titles = _fetch_rss_titles(
        theme_keywords, delay=rss_delay, lookback_days=lookback_days
    )

    logger.info("--- [2/3] PTT 股版 ---")
    ptt_titles = _fetch_ptt_texts(pages=ptt_pages, delay=ptt_delay)

    logger.info("--- [3/3] 鉅亨網 Anue ---")
    anue_titles, anue_stock_sets = _fetch_anue_data(
        limit_per_category=anue_limit, delay=anue_delay
    )

    # 3. 計算提及次數
    all_titles = rss_titles + ptt_titles + anue_titles
    logger.info(
        f"合計標題數：RSS={len(rss_titles)} PTT={len(ptt_titles)} Anue={len(anue_titles)}"
    )

    keyword_counts = _count_keyword_mentions(all_titles, theme_keywords)
    anue_direct_counts = _count_anue_stock_mentions(anue_stock_sets, stock_tag_map)

    # 合併（關鍵字比對 + Anue 直接股票標記）
    tag_mention_count: dict[str, int] = defaultdict(int)
    for tag_id, count in keyword_counts.items():
        tag_mention_count[tag_id] += count
    for tag_id, count in anue_direct_counts.items():
        tag_mention_count[tag_id] += count

    # 4. 排名，只保留有股票對應的主題
    hot_tags = [
        (tag_id, count)
        for tag_id, count in tag_mention_count.items()
        if count > 0 and tag_id in stock_tag_map
    ]
    hot_tags.sort(key=lambda x: x[1], reverse=True)
    hot_tags = hot_tags[:top_k]

    if not hot_tags:
        logger.warning("無任何主題有新聞提及，hot_stocks.csv 不會生成")
        return False

    # 5. 組成 DataFrame
    today = datetime.now().strftime("%Y-%m-%d")
    rows = []
    for rank, (tag_id, mention_count) in enumerate(hot_tags, 1):
        stock_ids = sorted(stock_tag_map.get(tag_id, set()))
        tag_name = tag_names.get(tag_id, tag_id)
        tag_type = theme_keywords.get(tag_id, {}).get("tag_type", "theme")
        stocks_str = "、".join(
            f"{STOCK_NAMES.get(sid, sid)}({sid})"
            for sid in stock_ids
        )
        rows.append({
            "rank": rank,
            "tag_id": tag_id,
            "tag_name": tag_name,
            "tag_type": tag_type,
            "mention_count": mention_count,
            "stock_count": len(stock_ids),
            "stocks": stocks_str,
            "snapshot_date": today,
        })

    df = pd.DataFrame(rows)

    # 6. 輸出 CSV
    os.makedirs(
        os.path.dirname(output_path) if os.path.dirname(output_path) else ".",
        exist_ok=True,
    )
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    logger.info(f"✅ hot_stocks.csv 已生成：{output_path}（{len(df)} 個主題）")

    for _, row in df.iterrows():
        logger.info(
            f"  #{row['rank']} {row['tag_name']} "
            f"mention={row['mention_count']} stocks={row['stock_count']}"
        )

    return True
