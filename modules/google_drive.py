"""
Google Drive 操作模組 - 處理檔案上傳下載和同步
"""
import os
import io
import json
import tempfile
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from .config import (
    OAUTH_CREDENTIALS,
    GDRIVE_SCOPES,
    GOOGLE_DRIVE_FOLDER_ID,
    GDRIVE_FOLDER_ID,
    GDRIVE_FOLDER_NAME,
    GDRIVE_DATA_FOLDER,
    DB_PATH,
    DEBUG_MODE
)
from .logger import get_logger

logger = get_logger(__name__)


# ===== OAuth 認證 =====

def get_drive_service():
    """建立 Google Drive API 服務（使用 OAuth 2.0）"""
    if not OAUTH_CREDENTIALS:
        raise ValueError("未設定 OAUTH 環境變數，無法進行 Google Drive 認證")

    try:
        logger.info("🔐 Google Drive OAuth 2.0 認證...")
        oauth_data = json.loads(OAUTH_CREDENTIALS)

        creds = Credentials(
            token=oauth_data.get('token'),
            refresh_token=oauth_data.get('refresh_token'),
            token_uri=oauth_data.get('token_uri'),
            client_id=oauth_data.get('client_id'),
            client_secret=oauth_data.get('client_secret'),
            scopes=GDRIVE_SCOPES
        )

        if creds.expired and creds.refresh_token:
            logger.info("🔄 重新整理 Google Drive 授權...")
            creds.refresh(Request())

        service = build('drive', 'v3', credentials=creds)
        logger.info("✅ Google Drive OAuth 認證成功")
        return service
    except Exception as e:
        logger.error(f"❌ OAuth 認證失敗: {e}")
        raise


# ===== 資料夾管理 =====

def find_folder(service, folder_name, parent_id=None):
    """尋找指定名稱的資料夾"""
    if not service:
        return None

    try:
        query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        if parent_id:
            query += f" and '{parent_id}' in parents"

        logger.debug(f"尋找資料夾查詢: {query}")
        results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        items = results.get('files', [])

        if items:
            logger.debug(f"找到資料夾: {folder_name}, ID: {items[0]['id']}")
            return items[0]['id']
        logger.debug(f"未找到資料夾: {folder_name}")
        return None
    except Exception as e:
        logger.error(f"❌ 尋找資料夾失敗: {e}")
        if DEBUG_MODE:
            logger.debug(f"詳細錯誤: {str(e)}", exc_info=True)
        return None


def create_folder(service, folder_name, parent_id=None):
    """建立資料夾"""
    if not service:
        return None

    try:
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        if parent_id:
            file_metadata['parents'] = [parent_id]

        logger.debug(f"建立資料夾: {folder_name}, parent_id: {parent_id}")
        folder = service.files().create(body=file_metadata, fields='id').execute()
        folder_id = folder.get('id')
        logger.info(f"✅ 已建立資料夾: {folder_name}, ID: {folder_id}")
        return folder_id
    except Exception as e:
        logger.error(f"❌ 建立資料夾失敗: {folder_name}, 錯誤: {e}")
        if DEBUG_MODE:
            logger.debug(f"詳細錯誤: {str(e)}", exc_info=True)
        return None


def setup_google_drive_folders(service):
    """設定 Google Drive 資料夾結構"""
    if not service:
        logger.warning("Google Drive service 不可用")
        return None

    try:
        # 如果有直接指定資料夾 ID，優先使用（支援兩種變數名稱）
        folder_id = GOOGLE_DRIVE_FOLDER_ID or GDRIVE_FOLDER_ID
        if folder_id:
            logger.info(f"✅ 使用指定的 Google Drive 資料夾 ID: {folder_id}")
            main_folder_id = folder_id
        else:
            # 尋找或建立主資料夾 stocks-autobot-data
            logger.info(f"🔍 搜尋資料夾: {GDRIVE_FOLDER_NAME}")
            main_folder_id = find_folder(service, GDRIVE_FOLDER_NAME)
            if not main_folder_id:
                logger.info(f"資料夾不存在，嘗試建立: {GDRIVE_FOLDER_NAME}")
                main_folder_id = create_folder(service, GDRIVE_FOLDER_NAME)

            if not main_folder_id:
                logger.error("❌ 無法建立主資料夾")
                return None

        # 尋找或建立 data 子資料夾
        logger.debug(f"尋找子資料夾: {GDRIVE_DATA_FOLDER} in {main_folder_id}")
        data_folder_id = find_folder(service, GDRIVE_DATA_FOLDER, main_folder_id)
        if not data_folder_id:
            logger.info(f"子資料夾不存在，嘗試建立: {GDRIVE_DATA_FOLDER}")
            data_folder_id = create_folder(service, GDRIVE_DATA_FOLDER, main_folder_id)

        if data_folder_id:
            logger.info(f"✅ Google Drive 資料夾已準備就緒: {GDRIVE_DATA_FOLDER} (ID: {data_folder_id})")
        else:
            logger.error(f"❌ 無法取得或建立 data 資料夾")

        return data_folder_id

    except Exception as e:
        logger.error(f"❌ 設定 Google Drive 資料夾失敗: {e}")
        if DEBUG_MODE:
            logger.debug(f"詳細錯誤: {str(e)}", exc_info=True)
        return None


# ===== 檔案下載 =====

def download_file_from_drive(service, file_name, folder_id, local_path):
    """從 Google Drive 下載檔案"""
    if not service:
        logger.warning("Google Drive 服務不可用")
        return False

    try:
        # 尋找檔案
        logger.debug(f"搜尋檔案: {file_name} 在資料夾: {folder_id}")
        query = f"name='{file_name}' and '{folder_id}' in parents and trashed=false"
        results = service.files().list(q=query, fields='files(id, name, size, modifiedTime)').execute()
        items = results.get('files', [])

        if not items:
            logger.info(f"📁 Google Drive 中找不到檔案: {file_name}")
            return False

        file_id = items[0]['id']
        file_size = int(items[0].get('size', 0)) / 1024 / 1024  # MB
        logger.debug(f"找到檔案 - ID: {file_id}, 大小: {file_size:.2f} MB")

        # 下載檔案
        logger.info(f"開始下載: {file_name}")
        request = service.files().get_media(fileId=file_id)
        file_buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(file_buffer, request)

        done = False
        while done is False:
            status, done = downloader.next_chunk()
            if DEBUG_MODE and status:
                logger.debug(f"下載進度: {int(status.progress() * 100)}%")

        # 寫入本地檔案
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, 'wb') as f:
            f.write(file_buffer.getvalue())

        logger.info(f"✅ 已從 Google Drive 下載: {file_name} -> {local_path}")
        logger.info(f"📥 下載完成 - 檔案大小: {file_size:.2f} MB")
        return True

    except Exception as e:
        logger.error(f"❌ 下載檔案失敗: {e}")
        if DEBUG_MODE:
            logger.debug(f"詳細錯誤: {str(e)}", exc_info=True)
        return False


# ===== 檔案上傳 =====

def upload_file_to_drive(service, local_path, file_name, folder_id):
    """上傳檔案到 Google Drive"""
    if not service:
        logger.warning("Google Drive 服務不可用")
        return False

    try:
        # 取得本地檔案大小
        file_size = os.path.getsize(local_path) / 1024 / 1024  # MB
        logger.debug(f"準備上傳檔案: {file_name}, 大小: {file_size:.2f} MB")

        # 檢查檔案是否已存在
        logger.debug(f"檢查檔案是否已存在: {file_name}")
        query = f"name='{file_name}' and '{folder_id}' in parents and trashed=false"
        results = service.files().list(q=query, fields='files(id, name)').execute()
        items = results.get('files', [])

        file_metadata = {'name': file_name, 'parents': [folder_id]}
        media = MediaFileUpload(local_path, resumable=True)

        if items:
            # 更新現有檔案
            file_id = items[0]['id']
            logger.info(f"更新現有檔案: {file_name} (ID: {file_id})")
            file = service.files().update(fileId=file_id, media_body=media).execute()
            logger.info(f"✅ 已更新 Google Drive 檔案: {file_name}")
            logger.info(f"📤 更新完成 - 檔案大小: {file_size:.2f} MB")
        else:
            # 建立新檔案
            logger.info(f"建立新檔案: {file_name}")
            file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            logger.info(f"✅ 已上傳新檔案到 Google Drive: {file_name}")
            logger.info(f"📤 上傳完成 - 檔案ID: {file.get('id')}, 大小: {file_size:.2f} MB")

        return True

    except Exception as e:
        logger.error(f"❌ 上傳檔案失敗: {e}")
        if DEBUG_MODE:
            logger.debug(f"檔案路徑: {local_path}")
            logger.debug(f"目標資料夾: {folder_id}")
            logger.debug(f"詳細錯誤: {str(e)}", exc_info=True)
        return False


def upload_to_google_drive(file_path: str, filename: str, folder_id: str, mimetype: str = 'image/png') -> str:
    """上傳檔案到 Google Drive 並返回分享連結"""
    logger.info(f"📤 上傳檔案到 Google Drive: {filename}")

    try:
        service = get_drive_service()

        # 取得檔案大小
        file_size = os.path.getsize(file_path) / 1024 / 1024  # MB
        logger.debug(f"檔案大小: {file_size:.2f} MB, 類型: {mimetype}")

        file_metadata = {
            'name': filename,
            'parents': [folder_id]
        }

        media = MediaFileUpload(file_path, mimetype=mimetype, resumable=True)
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()

        file_id = file.get('id')
        logger.debug(f"檔案已建立, ID: {file_id}")

        # 設定分享權限
        logger.debug("設定檔案為公開分享")
        service.permissions().create(
            fileId=file_id,
            body={'type': 'anyone', 'role': 'reader'}
        ).execute()

        web_link = file.get('webViewLink')
        logger.info(f"✅ 檔案上傳成功: {filename}")
        logger.info(f"🔗 分享連結: {web_link}")

        return web_link
    except Exception as e:
        logger.error(f"❌ Google Drive 上傳失敗: {e}")
        if DEBUG_MODE:
            logger.debug(f"檔案路徑: {file_path}")
            logger.debug(f"目標資料夾: {folder_id}")
            logger.debug(f"詳細錯誤: {str(e)}", exc_info=True)
        return None


def upload_text_to_google_drive(text_content: str, filename: str, folder_id: str) -> str:
    """將文字內容存為 txt 並上傳到 Google Drive"""
    logger.info(f"📄 準備上傳文字檔案: {filename}")

    try:
        # 建立暫存檔案
        temp_file = tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, suffix='.txt')
        temp_file.write(text_content)
        temp_file.close()

        logger.debug(f"暫存檔案建立: {temp_file.name}")
        logger.debug(f"文字內容大小: {len(text_content)} 字元")

        # 上傳到 Google Drive
        result = upload_to_google_drive(temp_file.name, filename, folder_id, mimetype='text/plain')

        # 刪除暫存檔案
        os.unlink(temp_file.name)
        logger.debug("暫存檔案已刪除")

        if result:
            logger.info(f"✅ 文字檔案上傳成功: {filename}")
        else:
            logger.error(f"❌ 文字檔案上傳失敗: {filename}")

        return result
    except Exception as e:
        logger.error(f"❌ 上傳文字檔失敗: {e}")
        if DEBUG_MODE:
            logger.debug(f"檔案名稱: {filename}")
            logger.debug(f"文字長度: {len(text_content)}")
            logger.debug(f"詳細錯誤: {str(e)}", exc_info=True)
        return None


# ===== 資料庫同步 =====

def sync_database_from_drive(service):
    """從 Google Drive 同步資料庫到本地"""
    logger.info("📥 開始從 Google Drive 同步資料庫")

    if not service:
        logger.warning("⚠️  跳過 Google Drive 下載（Service 不可用）")
        return False

    try:
        logger.debug("設定 Google Drive 資料夾結構")
        data_folder_id = setup_google_drive_folders(service)
        if not data_folder_id:
            logger.error("無法取得 Google Drive data 資料夾 ID")
            return False

        logger.debug(f"Data 資料夾 ID: {data_folder_id}")

        # 下載 taiex.sqlite
        logger.info("下載 taiex.sqlite 檔案")
        success = download_file_from_drive(service, "taiex.sqlite", data_folder_id, DB_PATH)

        if success:
            logger.info("✅ 資料庫從 Google Drive 同步成功")
            if DEBUG_MODE:
                file_size = os.path.getsize(DB_PATH) / 1024 / 1024  # MB
                logger.debug(f"資料庫檔案大小: {file_size:.2f} MB")
        else:
            logger.warning("⚠️  資料庫同步失敗或檔案不存在")

        return success

    except Exception as e:
        logger.error(f"❌ 從 Google Drive 同步資料庫失敗: {e}")
        if DEBUG_MODE:
            logger.debug(f"詳細錯誤: {str(e)}", exc_info=True)
        return False


def sync_line_ids_from_drive(service):
    """從 Google Drive 同步 line_id.txt 到本地"""
    logger.info("📥 開始從 Google Drive 同步 line_id.txt")

    if not service:
        logger.warning("⚠️  跳過 Google Drive 下載（Service 不可用）")
        return False

    try:
        logger.debug("設定 Google Drive 資料夾結構")
        data_folder_id = setup_google_drive_folders(service)
        if not data_folder_id:
            logger.error("無法取得 Google Drive data 資料夾 ID")
            return False

        logger.debug(f"Data 資料夾 ID: {data_folder_id}")

        # 下載 line_id.txt
        line_id_path = os.path.join(os.path.dirname(DB_PATH), "..", "line_id.txt")
        line_id_path = os.path.normpath(line_id_path)

        logger.info("下載 line_id.txt 檔案")
        success = download_file_from_drive(service, "line_id.txt", data_folder_id, line_id_path)

        if success:
            logger.info("✅ line_id.txt 從 Google Drive 同步成功")
        else:
            logger.warning("⚠️  line_id.txt 同步失敗或檔案不存在")

        return success

    except Exception as e:
        logger.error(f"❌ 從 Google Drive 同步 line_id.txt 失敗: {e}")
        if DEBUG_MODE:
            logger.debug(f"詳細錯誤: {str(e)}", exc_info=True)
        return False


def sync_database_to_drive(service):
    """上傳本地資料庫到 Google Drive"""
    logger.info("📤 開始上傳資料庫到 Google Drive")

    if not service:
        logger.warning("⚠️  跳過 Google Drive 上傳（Service 不可用）")
        return False

    try:
        if not os.path.exists(DB_PATH):
            logger.warning(f"⚠️  本地資料庫不存在: {DB_PATH}")
            return False

        # 取得檔案大小
        file_size = os.path.getsize(DB_PATH) / 1024 / 1024  # MB
        logger.info(f"資料庫檔案大小: {file_size:.2f} MB")

        logger.debug("設定 Google Drive 資料夾結構")
        data_folder_id = setup_google_drive_folders(service)
        if not data_folder_id:
            logger.error("無法取得 Google Drive data 資料夾 ID")
            return False

        logger.debug(f"Data 資料夾 ID: {data_folder_id}")

        # 上傳 taiex.sqlite
        logger.info("開始上傳 taiex.sqlite 到 Google Drive")
        success = upload_file_to_drive(service, DB_PATH, "taiex.sqlite", data_folder_id)

        if success:
            logger.info("✅ 資料庫成功上傳到 Google Drive")
            logger.info(f"📊 上傳完成 - 檔案: taiex.sqlite, 大小: {file_size:.2f} MB")
        else:
            logger.error("❌ 資料庫上傳失敗")

        return success

    except Exception as e:
        logger.error(f"❌ 上傳資料庫到 Google Drive 失敗: {e}")
        if DEBUG_MODE:
            logger.debug(f"詳細錯誤: {str(e)}", exc_info=True)
        return False