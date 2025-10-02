"""
配置模組 - 集中管理所有環境變數和設定
"""
import os
import re
from dotenv import load_dotenv

load_dotenv()

# ===== Debug 設定 =====
DEBUG_MODE = os.environ.get("DEBUG_MODE", "false").lower() == "true"

# ===== 資料庫設定 =====
DATA_DIR = os.environ.get("DATA_DIR", "data")
DB_PATH = "taiex.sqlite"  # 資料庫存在根目錄

# ===== LINE 設定 =====
LINE_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_USER_ID = os.environ.get("LINE_USER_ID", "").strip()

# ===== Google Drive 設定 =====
def extract_folder_id_from_url(folder_input):
    """從 Google Drive URL 或直接 ID 中提取 folder ID"""
    if not folder_input:
        return None

    # 如果是完整的 Google Drive URL，提取 folder ID
    if "drive.google.com" in folder_input:
        # 匹配各種 Google Drive URL 格式
        patterns = [
            r"/folders/([a-zA-Z0-9_-]+)",  # /folders/ID
            r"[?&]id=([a-zA-Z0-9_-]+)",   # ?id=ID 或 &id=ID
            r"[?&]folder_id=([a-zA-Z0-9_-]+)"  # folder_id=ID
        ]
        for pattern in patterns:
            match = re.search(pattern, folder_input)
            if match:
                extracted_id = match.group(1)
                return extracted_id
        return None

    # 如果已經是純 ID 格式，直接回傳
    return folder_input

GDRIVE_FOLDER_ID = extract_folder_id_from_url(os.environ.get("GDRIVE_FOLDER_ID"))
GOOGLE_DRIVE_FOLDER_ID = extract_folder_id_from_url(os.environ.get("GOOGLE_DRIVE_FOLDER_ID")) or GDRIVE_FOLDER_ID
GDRIVE_FOLDER_NAME = "stocks-autobot-data"  # 預設資料夾名稱（備用）
GDRIVE_DATA_FOLDER = "data"  # 在主資料夾下的子資料夾

# Google Drive 認證設定（支援兩種方式）
OAUTH_CREDENTIALS = os.environ.get("OAUTH")  # OAuth 2.0 認證
GDRIVE_SERVICE_ACCOUNT = os.environ.get("GDRIVE_SERVICE_ACCOUNT")  # Service Account 認證
GDRIVE_SCOPES = ['https://www.googleapis.com/auth/drive']

# ===== 環境檢測 =====
IN_GITHUB_ACTIONS = os.environ.get("GITHUB_ACTIONS") == "true"