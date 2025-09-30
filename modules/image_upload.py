"""
圖床上傳模組 - 上傳圖片到公開圖床
"""
import requests
from .logger import get_logger

logger = get_logger(__name__)


def upload_to_telegraph(image_path: str) -> str:
    """
    使用 Telegraph 上傳圖片（無需 API key）

    Args:
        image_path: 圖片路徑

    Returns:
        str: 圖片 URL，失敗返回 None
    """
    try:
        with open(image_path, 'rb') as f:
            response = requests.post(
                'https://telegra.ph/upload',
                files={'file': ('image.png', f, 'image/png')},
                timeout=30
            )

        if response.status_code == 200:
            result = response.json()
            if isinstance(result, list) and len(result) > 0:
                path = result[0].get('src')
                if path:
                    return f"https://telegra.ph{path}"

        logger.warning(f"Telegraph 上傳失敗: {response.status_code} - {response.text[:200]}")
    except Exception as e:
        logger.error(f"Telegraph 上傳異常: {e}")
    return None


def upload_to_catbox(image_path: str) -> str:
    """
    使用 Catbox 上傳圖片（無需 API key，備用）

    Args:
        image_path: 圖片路徑

    Returns:
        str: 圖片 URL，失敗返回 None
    """
    try:
        with open(image_path, 'rb') as f:
            response = requests.post(
                'https://catbox.moe/user/api.php',
                data={'reqtype': 'fileupload'},
                files={'fileToUpload': f},
                timeout=30
            )

        if response.status_code == 200:
            url = response.text.strip()
            if url.startswith('https://'):
                return url

        logger.warning(f"Catbox 上傳失敗: {response.status_code} - {response.text[:200]}")
    except Exception as e:
        logger.error(f"Catbox 上傳異常: {e}")
    return None


def upload_image(image_path: str) -> str:
    """
    嘗試多個圖床上傳，返回第一個成功的 URL

    Args:
        image_path: 圖片路徑

    Returns:
        str: 圖片 URL，全部失敗返回 None
    """
    logger.info(f"嘗試上傳圖片: {image_path}")

    # 優先使用 Telegraph
    url = upload_to_telegraph(image_path)
    if url:
        logger.info(f"✅ Telegraph 上傳成功: {url}")
        return url

    # 備用方案：Catbox
    logger.info("→ 嘗試備用圖床 Catbox...")
    url = upload_to_catbox(image_path)
    if url:
        logger.info(f"✅ Catbox 上傳成功: {url}")
        return url

    logger.error("❌ 所有圖床上傳失敗")
    return None