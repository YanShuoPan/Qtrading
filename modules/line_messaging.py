"""
LINE 訊息推送模組 - 處理 LINE Bot 訊息發送
"""
import os
import requests
import sqlite3
from .config import LINE_TOKEN, LINE_USER_ID, DB_PATH
from .logger import get_logger

logger = get_logger(__name__)


# ===== LINE ID 檔案讀取 =====

def read_line_ids_from_file():
    """從 line_id.txt 讀取 LINE User IDs"""
    line_id_file = os.path.join(os.path.dirname(DB_PATH), "..", "line_id.txt")
    line_id_file = os.path.normpath(line_id_file)

    user_ids = []

    if not os.path.exists(line_id_file):
        logger.warning(f"⚠️  line_id.txt 不存在: {line_id_file}")
        return user_ids

    try:
        with open(line_id_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or ':' not in line:
                    continue
                # 格式: name : USER_ID
                parts = line.split(':', 1)
                if len(parts) == 2:
                    name = parts[0].strip()
                    user_id = parts[1].strip()
                    if user_id:
                        user_ids.append({"user_id": user_id, "display_name": name})
                        logger.debug(f"讀取 LINE ID: {name} -> {user_id}")

        logger.info(f"✅ 從 line_id.txt 讀取到 {len(user_ids)} 個 LINE ID")
    except Exception as e:
        logger.error(f"❌ 讀取 line_id.txt 失敗: {e}")

    return user_ids


# ===== 基礎訊息發送函數 =====

def line_push_text_to(user_id: str, msg: str):
    """
    發送文字訊息給指定用戶

    Args:
        user_id: LINE 用戶 ID
        msg: 訊息內容
    """
    if not LINE_TOKEN:
        raise RuntimeError("LINE_CHANNEL_ACCESS_TOKEN is missing.")
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Authorization": f"Bearer {LINE_TOKEN}", "Content-Type": "application/json"}
    body = {"to": user_id, "messages": [{"type": "text", "text": msg}]}
    r = requests.post(url, headers=headers, json=body, timeout=30)
    r.raise_for_status()


def push_image_to(user_id: str, original_url: str, preview_url: str):
    """
    發送圖片訊息給指定用戶

    Args:
        user_id: LINE 用戶 ID
        original_url: 原圖 URL
        preview_url: 預覽圖 URL
    """
    if not LINE_TOKEN:
        raise RuntimeError("LINE_CHANNEL_ACCESS_TOKEN is missing.")
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Authorization": f"Bearer {LINE_TOKEN}", "Content-Type": "application/json"}
    body = {
        "to": user_id,
        "messages": [{
            "type": "image",
            "originalContentUrl": original_url,
            "previewImageUrl": preview_url
        }]
    }
    r = requests.post(url, headers=headers, json=body, timeout=30)
    r.raise_for_status()


# ===== 廣播函數 =====

def broadcast_text(msg: str, user_ids: list[str]):
    """
    廣播文字訊息給多個用戶

    Args:
        msg: 訊息內容
        user_ids: 用戶 ID 列表
    """
    ok, fail = 0, 0
    for uid in user_ids:
        try:
            line_push_text_to(uid, msg)
            ok += 1
        except Exception as e:
            logger.error(f"❌ push 給 {uid} 失敗: {e}")
            fail += 1
    logger.info(f"📨 文字廣播完成：成功 {ok}、失敗 {fail}")


def broadcast_image(url: str, user_ids: list[str]):
    """
    廣播圖片訊息給多個用戶

    Args:
        url: 圖片 URL
        user_ids: 用戶 ID 列表
    """
    ok, fail = 0, 0
    for uid in user_ids:
        try:
            push_image_to(uid, url, url)
            ok += 1
        except Exception as e:
            logger.error(f"❌ 圖片推送給 {uid} 失敗: {e}")
            fail += 1
    logger.info(f"🖼️ 圖片廣播完成：成功 {ok}、失敗 {fail}")


# ===== 訂閱者管理 =====

def get_active_subscribers():
    """取得所有活躍的訂閱者（優先從 line_id.txt，再從資料庫，最後用環境變數）"""
    subscribers = []

    # 優先從 line_id.txt 讀取
    subscribers = read_line_ids_from_file()
    if subscribers:
        logger.info(f"✅ 使用 line_id.txt 中的 {len(subscribers)} 個訂閱者")
        return subscribers

    # 如果 line_id.txt 沒有，從資料庫讀取
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute(
                "SELECT user_id, display_name FROM subscribers WHERE active = 1"
            )
            for row in cursor:
                subscribers.append({"user_id": row[0], "display_name": row[1]})
        if subscribers:
            logger.info(f"✅ 從資料庫讀取到 {len(subscribers)} 個訂閱者")
            return subscribers
    except Exception as e:
        logger.error(f"❌ 讀取資料庫訂閱者失敗: {e}")

    # 最後備用：使用環境變數
    if LINE_USER_ID:
        subscribers = [{"user_id": LINE_USER_ID, "display_name": "Default"}]
        logger.warning("⚠️  使用 LINE_USER_ID 環境變數作為備用")

    return subscribers


# ===== 多用戶發送函數（向後兼容）=====

def push_image(original_url: str, preview_url: str, user_id: str = None):
    """
    發送圖片給指定用戶或所有訂閱者

    Args:
        original_url: 原圖 URL
        preview_url: 預覽圖 URL
        user_id: 指定用戶 ID，如果為 None 則發送給所有訂閱者
    """
    if user_id:
        # 發送給單一用戶
        push_image_to(user_id, original_url, preview_url)
    else:
        # 發送給所有訂閱者
        subscribers = get_active_subscribers()
        if not subscribers:
            # 如果沒有訂閱者，使用 LINE_USER_ID 作為備用
            if LINE_USER_ID:
                push_image_to(LINE_USER_ID, original_url, preview_url)
                logger.warning("使用 LINE_USER_ID 作為備用發送目標")
            return

        for subscriber in subscribers:
            try:
                push_image_to(subscriber["user_id"], original_url, preview_url)
                logger.info(f"[OK] 圖片已發送給 {subscriber['display_name'] or subscriber['user_id']}")
            except Exception as e:
                logger.error(f"[ERROR] 發送圖片給 {subscriber['display_name'] or subscriber['user_id']} 失敗: {e}")


def line_push_text(msg: str, user_id: str = None):
    """
    發送文字訊息給指定用戶或所有訂閱者

    Args:
        msg: 訊息內容
        user_id: 指定用戶 ID，如果為 None 則發送給所有訂閱者
    """
    if user_id:
        # 發送給單一用戶
        line_push_text_to(user_id, msg)
    else:
        # 發送給所有訂閱者
        subscribers = get_active_subscribers()
        if not subscribers:
            # 如果沒有訂閱者，使用 LINE_USER_ID 作為備用
            if LINE_USER_ID:
                line_push_text_to(LINE_USER_ID, msg)
                logger.warning("使用 LINE_USER_ID 作為備用發送目標")
            return

        for subscriber in subscribers:
            try:
                line_push_text_to(subscriber["user_id"], msg)
                logger.info(f"[OK] 訊息已發送給 {subscriber['display_name'] or subscriber['user_id']}")
            except Exception as e:
                logger.error(f"[ERROR] 發送訊息給 {subscriber['display_name'] or subscriber['user_id']} 失敗: {e}")