"""
Groq AI 情緒分析模組

使用 Groq API（llama-3.3-70b-versatile）對新聞標題進行台股情緒分析，
分類為 bullish / bearish / neutral，並給出 1-10 分的情緒分數。
"""

import json
import time

from .config import GROQ_API_KEY
from .logger import get_logger

logger = get_logger(__name__)

_NEUTRAL_DEFAULT = {"sentiment": "neutral", "score": 5, "reason": "API key 未設定"}

_PROMPT_TEMPLATE = """你是台股市場情緒分析器。分析以下新聞標題對相關股票的影響。
請回傳純 JSON（不要 markdown），格式：
{{"sentiment": "bullish/bearish/neutral", "score": 1-10, "reason": "一句話理由"}}
score 說明：1=極度看空, 5=中性, 10=極度看多
新聞標題：
{titles}"""

_VALID_SENTIMENTS = {"bullish", "bearish", "neutral"}


def analyze_sentiment(titles: list[str]) -> dict:
    """
    使用 Groq API 分析新聞標題列表的台股情緒。

    Args:
        titles: 新聞標題列表

    Returns:
        {"sentiment": str, "score": int, "reason": str}
        sentiment 為 bullish / bearish / neutral 之一
    """
    if not GROQ_API_KEY:
        return dict(_NEUTRAL_DEFAULT)

    if not titles:
        return {"sentiment": "neutral", "score": 5, "reason": "無新聞標題"}

    # 最多取 15 則標題
    selected = titles[:15]
    bullet_list = "\n".join(f"- {t}" for t in selected)
    prompt = _PROMPT_TEMPLATE.format(titles=bullet_list)

    try:
        from groq import Groq

        client = Groq(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=256,
        )
        raw_text = response.choices[0].message.content.strip()
        logger.debug(f"Groq 回應: {raw_text}")

        result = json.loads(raw_text)

        # 驗證格式
        sentiment = str(result.get("sentiment", "neutral")).lower()
        if sentiment not in _VALID_SENTIMENTS:
            logger.warning(f"Groq 回傳不合法的 sentiment: {sentiment!r}，改用 neutral")
            sentiment = "neutral"

        score = int(result.get("score", 5))
        score = max(1, min(10, score))  # 確保在 1-10 之間

        reason = str(result.get("reason", ""))

        return {"sentiment": sentiment, "score": score, "reason": reason}

    except json.JSONDecodeError as e:
        logger.warning(f"Groq 回應 JSON 解析失敗: {e}")
        return {"sentiment": "neutral", "score": 5, "reason": f"JSON 解析失敗: {e}"}
    except Exception as e:
        logger.error(f"Groq API 呼叫失敗: {e}")
        return {"sentiment": "neutral", "score": 5, "reason": f"API 錯誤: {e}"}


def analyze_theme_sentiments(hot_stocks_info: dict) -> dict:
    """
    對每個題材主題執行情緒分析。

    先一次性批量抓取所有主題的 RSS 標題，再依關鍵字分配給各主題，
    避免逐主題重複抓取 RSS。

    Args:
        hot_stocks_info: load_hot_stocks() 的回傳值，格式：
            {code: {"tag_name": str, "mention_count": int, ...}}

    Returns:
        {tag_name: {"sentiment": str, "score": int, "reason": str}}
        若 GROQ_API_KEY 未設定，回傳空 dict。
    """
    if not GROQ_API_KEY:
        logger.info("GROQ_API_KEY 未設定，跳過主題情緒分析")
        return {}

    # 從 hot_stocks_info 中提取不重複的 tag_name
    tag_names: set[str] = set()
    for info in hot_stocks_info.values():
        tag_name = info.get("tag_name", "")
        if tag_name:
            tag_names.add(tag_name)

    if not tag_names:
        logger.info("hot_stocks_info 中無任何 tag_name，跳過情緒分析")
        return {}

    from .hot_stocks_generator import _fetch_rss_titles

    # 一次批量抓取所有主題的 RSS（而非 N 次個別抓取）
    all_theme_keywords = {
        tn: {"news_keywords": [tn]} for tn in sorted(tag_names)
    }
    logger.info(f"批量抓取 {len(tag_names)} 個主題的 RSS 標題...")
    all_titles = _fetch_rss_titles(all_theme_keywords, delay=0.5, lookback_days=3)
    logger.info(f"共取得 {len(all_titles)} 篇不重複標題")

    results: dict[str, dict] = {}

    for i, tag_name in enumerate(sorted(tag_names)):
        try:
            # 從批量結果中篩選與主題相關的標題
            relevant = [t for t in all_titles if tag_name.lower() in t.lower()]
            if not relevant:
                relevant = all_titles[:10]

            sentiment_result = analyze_sentiment(relevant[:10])
            results[tag_name] = sentiment_result

        except Exception as e:
            logger.warning(f"主題 {tag_name!r} 情緒分析失敗: {e}")
            results[tag_name] = {
                "sentiment": "neutral",
                "score": 5,
                "reason": f"分析失敗: {e}",
            }

        # Groq rate limiting
        if i < len(tag_names) - 1:
            time.sleep(1)

    summary = {k: f"{v['sentiment']}({v['score']})" for k, v in results.items()}
    logger.info(f"情緒分析完成: {summary}")
    return results
