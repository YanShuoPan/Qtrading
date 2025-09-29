import os
import requests
import sqlite3
from datetime import datetime, timedelta, timezone
import tempfile
import base64
import json
import io
import logging

import pandas as pd
import numpy as np
import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from dotenv import load_dotenv
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

load_dotenv()

# Debug設定
DEBUG_MODE = os.environ.get("DEBUG_MODE", "false").lower() == "true"

# 設定日誌
if DEBUG_MODE:
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
        handlers=[
            logging.FileHandler('debug.log', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    print(f"🐛 DEBUG模式已啟用，詳細日誌將保存到 debug.log")
else:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

logger = logging.getLogger(__name__)
logger.info("=== 台股推薦機器人啟動 ===")
logger.info(f"DEBUG_MODE: {DEBUG_MODE}")

LINE_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_USER_ID = os.environ["LINE_USER_ID"]

DATA_DIR = os.environ.get("DATA_DIR", "data")
DB_PATH = os.path.join(DATA_DIR, "taiex.sqlite")

# Google Drive 設定 - 支援直接指定資料夾 ID 或使用預設名稱搜尋
GDRIVE_FOLDER_ID = os.environ.get("GDRIVE_FOLDER_ID")
GOOGLE_DRIVE_FOLDER_ID = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", GDRIVE_FOLDER_ID)  # OAuth 版本相容
GDRIVE_FOLDER_NAME = "stocks-autobot-data"  # 預設資料夾名稱（備用）
GDRIVE_DATA_FOLDER = "data"  # 在主資料夾下的子資料夾

# Google Drive 認證設定（支援兩種方式）
OAUTH_CREDENTIALS = os.environ.get("OAUTH")  # OAuth 2.0 認證
GDRIVE_SERVICE_ACCOUNT = os.environ.get("GDRIVE_SERVICE_ACCOUNT")  # Service Account 認證
SCOPES = ['https://www.googleapis.com/auth/drive']

# Use environment variable for stock codes, fallback to comprehensive list
DEFAULT_CODES = [
    "1101", "1102", "1103", "1104", "1108", "1109", "1110", "1201", "1203", "1210",
    "1213", "1215", "1216", "1217", "1218", "1219", "1220", "1225", "1227", "1229",
    "1231", "1232", "1233", "1234", "1235", "1236", "1256", "1301", "1303", "1304",
    "1305", "1307", "1308", "1309", "1310", "1312", "1313", "1314", "1315", "1316",
    "1319", "1321", "1323", "1324", "1325", "1326", "1337", "1338", "1339", "1340",
    "1341", "1342", "1402", "1409", "1410", "1413", "1414", "1416", "1417", "1418",
    "1419", "1423", "1432", "1434", "1435", "1436", "1437", "1438", "1439", "1440",
    "1441", "1442", "1443", "1444", "1445", "1446", "1447", "1449", "1451", "1452",
    "1453", "1454", "1455", "1456", "1457", "1459", "1460", "1463", "1464", "1465",
    "1466", "1467", "1468", "1470", "1471", "1472", "1473", "1474", "1475", "1476",
    "1477", "1503", "1504", "1506", "1512", "1513", "1514", "1515", "1516", "1517",
    "1519", "1521", "1522", "1524", "1525", "1526", "1527", "1528", "1529", "1530",
    "1531", "1532", "1533", "1535", "1536", "1537", "1538", "1539", "1540", "1541",
    "1558", "1560", "1563", "1568", "1582", "1583", "1587", "1589", "1590", "1597",
    "1598", "1603", "1604", "1605", "1608", "1609", "1611", "1612", "1614", "1615",
    "1616", "1617", "1618", "1626", "1702", "1707", "1708", "1709", "1710", "1711",
    "1712", "1713", "1714", "1717", "1718", "1720", "1721", "1722", "1723", "1725",
    "1726", "1727", "1730", "1731", "1732", "1733", "1734", "1735", "1736", "1737",
    "1752", "1760", "1762", "1773", "1776", "1783", "1786", "1789", "1795", "1802",
    "1805", "1806", "1808", "1809", "1810", "1817", "1903", "1904", "1905", "1906",
    "1907", "1909", "2002", "2006", "2007", "2008", "2009", "2010", "2012", "2013",
    "2014", "2015", "2017", "2020", "2022", "2023", "2024", "2025", "2027", "2028",
    "2029", "2030", "2031", "2032", "2033", "2034", "2038", "2049", "2059", "2062",
    "2069", "2101", "2102", "2103", "2104", "2105", "2106", "2107", "2108", "2109",
    "2114", "2115", "2201", "2204", "2206", "2207", "2208", "2211", "2227", "2228",
    "2231", "2233", "2236", "2239", "2241", "2243", "2247", "2248", "2250", "2301",
    "2302", "2303", "2305", "2308", "2312", "2313", "2314", "2316", "2317", "2321",
    "2323", "2324", "2327", "2328", "2329", "2330", "2331", "2332", "2337", "2338",
    "2340", "2342", "2344", "2345", "2347", "2348", "2349", "2351", "2352", "2353",
    "2354", "2355", "2356", "2357", "2359", "2360", "2362", "2363", "2364", "2365"
]

CODES = os.environ.get("TWSE_CODES", ",".join(DEFAULT_CODES)).split(",")
PICKS_TOP_K = int(os.environ.get("TOP_K", "300"))

STOCK_NAMES = {
    "1101": "台泥", "1102": "亞泥", "1103": "嘉泥", "1104": "環泥", "1108": "幸福",
    "1109": "信大", "1110": "東泥", "1201": "味全", "1203": "味王", "1210": "大成",
    "1213": "大飲", "1215": "卜蜂", "1216": "統一", "1217": "愛之味", "1218": "泰山",
    "1219": "福壽", "1220": "台榮", "1225": "福懋油", "1227": "佳格", "1229": "聯華",
    "1231": "聯華食", "1232": "大統益", "1233": "天仁", "1234": "黑松", "1235": "興泰",
    "1236": "宏亞", "1256": "鮮活果汁-KY", "1301": "台塑", "1303": "南亞", "1304": "台聚",
    "1305": "華夏", "1307": "三芳", "1308": "亞聚", "1309": "台達化", "1310": "台苯",
    "1312": "國喬", "1313": "聯成", "1314": "中石化", "1315": "達新", "1316": "上曜",
    "1319": "東陽", "1321": "大洋", "1323": "永裕", "1324": "地球", "1325": "恆大",
    "1326": "台化", "1337": "再生-KY", "1338": "廣華-KY", "1339": "昭輝", "1340": "勝悅-KY",
    "1341": "富林-KY", "1342": "八貫", "1402": "遠東新", "1409": "新纖", "1410": "南染",
    "1413": "宏洲", "1414": "東和", "1416": "廣豐", "1417": "嘉裕", "1418": "東華",
    "1419": "新紡", "1423": "利華", "1432": "大魯閣", "1434": "福懋", "1435": "中福",
    "1436": "華友聯", "1437": "勤益控", "1438": "三地開發", "1439": "雋揚", "1440": "南紡",
    "1441": "大東", "1442": "名軒", "1443": "立益物流", "1444": "力麗", "1445": "大宇",
    "1446": "宏和", "1447": "力鵬", "1449": "佳和", "1451": "年興", "1452": "宏益",
    "1453": "大將", "1454": "台富", "1455": "集盛", "1456": "怡華", "1457": "宜進",
    "1459": "聯發", "1460": "宏遠", "1463": "強盛新", "1464": "得力", "1465": "偉全",
    "1466": "聚隆", "1467": "南緯", "1468": "昶和", "1470": "大統新創", "1471": "首利",
    "1472": "三洋實業", "1473": "台南", "1474": "弘裕", "1475": "業旺", "1476": "儒鴻",
    "1477": "聚陽", "1503": "士電", "1504": "東元", "1506": "正道", "1512": "瑞利",
    "1513": "中興電", "1514": "亞力", "1515": "力山", "1516": "川飛", "1517": "利奇",
    "1519": "華城", "1521": "大億", "1522": "堤維西", "1524": "耿鼎", "1525": "江申",
    "1526": "日馳", "1527": "鑽全", "1528": "恩德", "1529": "樂事綠能", "1530": "亞崴",
    "1531": "高林股", "1532": "勤美", "1533": "車王電", "1535": "中宇", "1536": "和大",
    "1537": "廣隆", "1538": "正峰", "1539": "巨庭", "1540": "喬福", "1541": "錩泰",
    "1558": "伸興", "1560": "中砂", "1563": "巧新", "1568": "倉佑", "1582": "信錦",
    "1583": "程泰", "1587": "吉茂", "1589": "永冠-KY", "1590": "亞德客-KY", "1597": "直得",
    "1598": "岱宇", "1603": "華電", "1604": "聲寶", "1605": "華新", "1608": "華榮",
    "1609": "大亞", "1611": "中電", "1612": "宏泰", "1614": "三洋電", "1615": "大山",
    "1616": "億泰", "1617": "榮星", "1618": "合機", "1626": "艾美特-KY", "1702": "南僑",
    "1707": "葡萄王", "1708": "東鹼", "1709": "和益", "1710": "東聯", "1711": "永光",
    "1712": "興農", "1713": "國化", "1714": "和桐", "1717": "長興", "1718": "中纖",
    "1720": "生達", "1721": "三晃", "1722": "台肥", "1723": "中碳", "1725": "元禎",
    "1726": "永記", "1727": "中華化", "1730": "花仙子", "1731": "美吾華", "1732": "毛寶",
    "1733": "五鼎", "1734": "杏輝", "1735": "日勝化", "1736": "喬山", "1737": "臺鹽",
    "1752": "南光", "1760": "寶齡富錦", "1762": "中化生", "1773": "勝一", "1776": "展宇",
    "1783": "和康生", "1786": "科妍", "1789": "神隆", "1795": "美時", "1802": "台玻",
    "1805": "寶徠", "1806": "冠軍", "1808": "潤隆", "1809": "中釉", "1810": "和成",
    "1817": "凱撒衛", "1903": "士紙", "1904": "正隆", "1905": "華紙", "1906": "寶隆",
    "1907": "永豐餘", "1909": "榮成", "2002": "中鋼", "2006": "東和鋼鐵", "2007": "燁興",
    "2008": "高興昌", "2009": "第一銅", "2010": "春源", "2012": "春雨", "2013": "中鋼構",
    "2014": "中鴻", "2015": "豐興", "2017": "官田鋼", "2020": "美亞", "2022": "聚亨",
    "2023": "燁輝", "2024": "志聯", "2025": "千興", "2027": "大成鋼", "2028": "威致",
    "2029": "盛餘", "2030": "彰源", "2031": "新光鋼", "2032": "新鋼", "2033": "佳大",
    "2034": "允強", "2038": "海光", "2049": "上銀", "2059": "川湖", "2062": "橋椿",
    "2069": "運錩", "2101": "南港", "2102": "泰豐", "2103": "台橡", "2104": "國際中橡",
    "2105": "正新", "2106": "建大", "2107": "厚生", "2108": "南帝", "2109": "華豐",
    "2114": "鑫永銓", "2115": "六暉-KY", "2201": "裕隆", "2204": "中華", "2206": "三陽工業",
    "2207": "和泰車", "2208": "台船", "2211": "長榮鋼", "2227": "裕日車", "2228": "劍麟",
    "2231": "為升", "2233": "宇隆", "2236": "百達-KY", "2239": "英利-KY", "2241": "艾姆勒",
    "2243": "宏旭-KY", "2247": "汎德永業", "2248": "華勝-KY", "2250": "IKKA-KY", "2301": "光寶科",
    "2302": "麗正", "2303": "聯電", "2305": "全友", "2308": "台達電", "2312": "金寶",
    "2313": "華通", "2314": "台揚", "2316": "楠梓電", "2317": "鴻海", "2321": "東訊",
    "2323": "中環", "2324": "仁寶", "2327": "國巨*", "2328": "廣宇", "2329": "華泰",
    "2330": "台積電", "2331": "精英", "2332": "友訊", "2337": "旺宏", "2338": "光罩",
    "2340": "台亞", "2342": "茂矽", "2344": "華邦電", "2345": "智邦", "2347": "聯強",
    "2348": "海悅", "2349": "錸德", "2351": "順德", "2352": "佳世達", "2353": "宏碁",
    "2354": "鴻準", "2355": "敬鵬", "2356": "英業達", "2357": "華碩", "2359": "所羅門",
    "2360": "致茂", "2362": "藍天", "2363": "矽統", "2364": "倫飛", "2365": "昆盈"
}


def push_image(original_url: str, preview_url: str):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Authorization": f"Bearer {LINE_TOKEN}", "Content-Type": "application/json"}
    body = {
        "to": LINE_USER_ID,
        "messages": [{
            "type": "image",
            "originalContentUrl": original_url,
            "previewImageUrl": preview_url
        }]
    }
    r = requests.post(url, headers=headers, json=body, timeout=30)
    r.raise_for_status()

def line_push_text(msg: str):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Authorization": f"Bearer {LINE_TOKEN}", "Content-Type": "application/json"}
    body = {"to": LINE_USER_ID, "messages": [{"type": "text", "text": msg}]}
    r = requests.post(url, headers=headers, json=body, timeout=30)
    r.raise_for_status()


def get_drive_service():
    """建立 Google Drive API 服務（使用 OAuth 2.0）"""
    if not OAUTH_CREDENTIALS:
        raise ValueError("未設定 OAUTH 環境變數，無法進行 Google Drive 認證")

    try:
        print("🔐 Google Drive OAuth 2.0 認證...")
        oauth_data = json.loads(OAUTH_CREDENTIALS)

        creds = Credentials(
            token=oauth_data.get('token'),
            refresh_token=oauth_data.get('refresh_token'),
            token_uri=oauth_data.get('token_uri'),
            client_id=oauth_data.get('client_id'),
            client_secret=oauth_data.get('client_secret'),
            scopes=SCOPES
        )

        if creds.expired and creds.refresh_token:
            print("🔄 重新整理 Google Drive 授權...")
            creds.refresh(Request())

        service = build('drive', 'v3', credentials=creds)
        print("✅ Google Drive OAuth 認證成功")
        return service
    except Exception as e:
        print(f"❌ OAuth 認證失敗: {e}")
        raise


def find_folder(service, folder_name, parent_id=None):
    """尋找指定名稱的資料夾"""
    if not service:
        return None

    try:
        query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        if parent_id:
            query += f" and '{parent_id}' in parents"

        results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        items = results.get('files', [])

        if items:
            return items[0]['id']
        return None
    except Exception as e:
        print(f"❌ 尋找資料夾失敗: {e}")
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

        folder = service.files().create(body=file_metadata, fields='id').execute()
        print(f"✅ 已建立資料夾: {folder_name}")
        return folder.get('id')
    except Exception as e:
        print(f"❌ 建立資料夾失敗: {e}")
        return None


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


def setup_google_drive_folders(service):
    """設定 Google Drive 資料夾結構"""
    if not service:
        return None

    try:
        # 如果有直接指定資料夾 ID，優先使用（支援兩種變數名稱）
        folder_id = GOOGLE_DRIVE_FOLDER_ID or GDRIVE_FOLDER_ID
        if folder_id:
            print(f"✅ 使用指定的 Google Drive 資料夾 ID: {folder_id}")
            main_folder_id = folder_id
        else:
            # 尋找或建立主資料夾 stocks-autobot-data
            print(f"🔍 搜尋資料夾: {GDRIVE_FOLDER_NAME}")
            main_folder_id = find_folder(service, GDRIVE_FOLDER_NAME)
            if not main_folder_id:
                main_folder_id = create_folder(service, GDRIVE_FOLDER_NAME)

            if not main_folder_id:
                print("❌ 無法建立主資料夾")
                return None

        # 尋找或建立 data 子資料夾
        data_folder_id = find_folder(service, GDRIVE_DATA_FOLDER, main_folder_id)
        if not data_folder_id:
            data_folder_id = create_folder(service, GDRIVE_DATA_FOLDER, main_folder_id)

        if data_folder_id:
            print(f"✅ Google Drive 資料夾已準備就緒: {GDRIVE_DATA_FOLDER}")

        return data_folder_id

    except Exception as e:
        print(f"❌ 設定 Google Drive 資料夾失敗: {e}")
        return None


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
                import os
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


def ensure_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS prices(
                code TEXT,
                date TEXT,
                open REAL, high REAL, low REAL, close REAL,
                volume INTEGER,
                PRIMARY KEY(code, date)
            )
            """
        )
        conn.commit()


def get_existing_data_range() -> dict:
    if not os.path.exists(DB_PATH):
        return {}
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT code, MIN(date) as min_date, MAX(date) as max_date FROM prices GROUP BY code"
        )
        result = {}
        for row in cursor:
            result[row[0]] = {"min": row[1], "max": row[2]}
    return result


def fetch_prices_yf(codes, lookback_days=120) -> pd.DataFrame:
    existing = get_existing_data_range()
    target_start = (datetime.utcnow() - timedelta(days=lookback_days * 2)).date().isoformat()

    codes_to_fetch = []
    for c in codes:
        c = c.strip()
        if not c:
            continue
        if c not in existing:
            codes_to_fetch.append(c)
            print(f"{c}: 無歷史資料，需下載")
        else:
            max_date = existing[c]["max"]
            if max_date < (datetime.utcnow() - timedelta(days=2)).date().isoformat():
                codes_to_fetch.append(c)
                print(f"{c}: 資料過舊 (最新: {max_date})，需更新")
            else:
                print(f"{c}: 資料已是最新 (最新: {max_date})")

    if not codes_to_fetch:
        print("所有股票資料都已是最新，無需下載")
        return pd.DataFrame()

    tickers = [f"{c}.TW" for c in codes_to_fetch]
    print(f"\n開始下載 {len(codes_to_fetch)} 支股票")
    print(f"期間: {target_start} ~ 今日")

    df = yf.download(
        tickers=" ".join(tickers),
        start=target_start,
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        progress=False,
    )
    out = []
    for c in codes_to_fetch:
        t = f"{c}.TW"
        if isinstance(df, pd.DataFrame) and t in df:
            tmp = df[t].reset_index().rename(columns=str.lower)
            if "date" in tmp.columns:
                tmp["date"] = pd.to_datetime(tmp["date"]).dt.tz_localize(None)
            tmp["code"] = c
            out.append(tmp[["code", "date", "open", "high", "low", "close", "volume"]])
    result = pd.concat(out, ignore_index=True) if out else pd.DataFrame()
    print(f"成功下載 {len(result)} 筆數據")
    return result


def upsert_prices(df: pd.DataFrame):
    if df.empty:
        return
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date.astype(str)
    with sqlite3.connect(DB_PATH) as conn:
        df.to_sql("_prices_in", conn, if_exists="replace", index=False)
        conn.execute("DELETE FROM prices WHERE (code, date) IN (SELECT code, date FROM _prices_in)")
        conn.execute(
            """
            INSERT INTO prices(code, date, open, high, low, close, volume)
            SELECT code, date, open, high, low, close, volume FROM _prices_in
            """
        )
        conn.execute("DROP TABLE _prices_in")
        conn.commit()
    print(f"數據已存入資料庫: {DB_PATH}")


def load_recent_prices(days=120) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query(
            "SELECT code, date, open, high, low, close, volume FROM prices",
            conn,
            parse_dates=["date"],
        )
    cutoff = datetime.utcnow() - timedelta(days=days)
    return df[df["date"] >= cutoff]


def pick_stocks(prices: pd.DataFrame, top_k=30) -> pd.DataFrame:
    if prices.empty:
        return pd.DataFrame()
    prices = prices.sort_values(["code", "date"])

    def add_feat(g):
        g = g.copy()
        g["ma20"] = g["close"].rolling(20, min_periods=20).mean()
        return g

    feat = prices.groupby("code", group_keys=False).apply(add_feat)

    results = []
    for code, group in feat.groupby("code"):
        group = group.sort_values("date")
        if len(group) < 5:
            continue

        last_5 = group.tail(5)
        if last_5["ma20"].isna().any():
            continue

        open_above = (last_5["open"] > last_5["ma20"]).all()
        close_above = (last_5["close"] > last_5["ma20"]).all()

        if not (open_above and close_above):
            continue

        ma20_values = last_5["ma20"].values
        ma20_slope = (ma20_values[-1] - ma20_values[0]) / 4

        if ma20_slope >= 1:
            continue
        price_std = last_5["close"].std()
        price_mean = last_5["close"].mean()
        volatility_pct = (price_std / price_mean * 100) if price_mean > 0 else 999
        if volatility_pct > 3.0:
            continue

        max_distance_allowed = max(2.0, volatility_pct * 1.5)

        min_price = last_5[["open", "close"]].min(axis=1)
        distance_pct = ((min_price - last_5["ma20"]) / last_5["ma20"] * 100)
        avg_distance = distance_pct.mean()

        if avg_distance > max_distance_allowed:
            continue

        avg_price = (last_5["open"] + last_5["close"]) / 2
        avg_ma20_distance = abs(avg_price - last_5["ma20"]).mean()

        latest = last_5.iloc[-1]
        is_lowest_close = latest["close"] == last_5["close"].min()

        results.append({
            "code": code,
            "close": latest["close"],
            "ma20": latest["ma20"],
            "distance": avg_distance,
            "volatility": volatility_pct,
            "ma20_slope": ma20_slope,
            "max_distance": max_distance_allowed,
            "volume": latest["volume"],
            "avg_ma20_distance": avg_ma20_distance,
            "is_lowest_close": is_lowest_close
        })

    if not results:
        return pd.DataFrame()

    result_df = pd.DataFrame(results)

    group1 = result_df[(result_df["ma20_slope"] >= 0.5) & (result_df["ma20_slope"] < 1)]
    group2 = result_df[result_df["ma20_slope"] < 0.5]

    if len(group1) > 6:
        group1_filtered = group1[group1["is_lowest_close"] == False]
        if len(group1_filtered) > 6:
            group1 = group1_filtered.nsmallest(6, "avg_ma20_distance")
        elif len(group1_filtered) > 0:
            group1 = group1_filtered
        else:
            group1 = group1.nsmallest(6, "avg_ma20_distance")

    if len(group2) > 6:
        group2_filtered = group2[group2["is_lowest_close"] == False]
        if len(group2_filtered) > 6:
            group2 = group2_filtered.nsmallest(6, "avg_ma20_distance")
        elif len(group2_filtered) > 0:
            group2 = group2_filtered
        else:
            group2 = group2.nsmallest(6, "avg_ma20_distance")

    final_result = pd.concat([group1, group2], ignore_index=True)
    return final_result


def plot_candlestick(ax, stock_data):
    """在指定的 ax 上繪製 K 棒圖"""
    stock_data = stock_data.copy().reset_index(drop=True)

    for idx, row in stock_data.iterrows():
        date_num = idx
        open_price = row['open']
        high_price = row['high']
        low_price = row['low']
        close_price = row['close']

        color = '#FF4444' if close_price >= open_price else '#00AA00'

        ax.plot([date_num, date_num], [low_price, high_price], color=color, linewidth=0.8)

        body_height = abs(close_price - open_price)
        body_bottom = min(open_price, close_price)
        ax.bar(date_num, body_height, bottom=body_bottom, color=color, width=0.6, alpha=0.8)


def plot_stock_charts(codes: list, prices: pd.DataFrame) -> str:
    """繪製最多 6 支股票的 K 棒圖（2x3 子圖）"""
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

    if DEBUG_MODE:
        logger.debug(f"matplotlib 後端: {matplotlib.get_backend()}")
        logger.debug(f"設定字體順序: {fonts}")

    fig, axes = plt.subplots(2, 3, figsize=(18, 12))
    axes = axes.flatten()

    for i, code in enumerate(codes):
        stock_data = prices[prices["code"] == code].sort_values("date").tail(90)

        if stock_data.empty or len(stock_data) < 20:
            axes[i].text(0.5, 0.5, f"{code} {STOCK_NAMES.get(code, '')}\n數據不足",
                        ha='center', va='center', fontsize=14)
            axes[i].set_xticks([])
            axes[i].set_yticks([])
            continue

        stock_data = stock_data.copy()
        stock_data["ma20"] = stock_data["close"].rolling(20, min_periods=20).mean()

        ax = axes[i]
        plot_candlestick(ax, stock_data)

        valid_ma20 = stock_data[stock_data["ma20"].notna()]
        if not valid_ma20.empty:
            ma20_indices = valid_ma20.index - stock_data.index[0]
            ax.plot(ma20_indices, valid_ma20["ma20"], label="MA20",
                   linewidth=2, linestyle="--", alpha=0.7, color='#2E86DE')

        stock_name = STOCK_NAMES.get(code, code)
        ax.set_title(f"{code} {stock_name}", fontsize=14, fontweight='bold', pad=10)
        ax.legend(fontsize=9, loc='upper left')
        ax.grid(True, alpha=0.3, linestyle='--')

        date_labels = stock_data["date"].dt.strftime('%m/%d').tolist()
        step = max(1, len(date_labels) // 6)
        tick_positions = list(range(0, len(date_labels), step))
        tick_labels = [date_labels[i] for i in tick_positions]
        ax.set_xticks(tick_positions)
        ax.set_xticklabels(tick_labels, rotation=45, fontsize=9)
        ax.tick_params(axis='y', labelsize=9)

    for i in range(n_stocks, 6):
        fig.delaxes(axes[i])

    plt.tight_layout()

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    plt.savefig(temp_file.name, dpi=100, bbox_inches='tight')
    plt.close()

    return temp_file.name


def upload_to_telegraph(image_path: str) -> str:
    """使用 Telegraph 上傳圖片（無需 API key）"""
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

        print(f"Telegraph 上傳失敗: {response.status_code} - {response.text[:200]}")
    except Exception as e:
        print(f"Telegraph 上傳異常: {e}")
    return None


def upload_to_catbox(image_path: str) -> str:
    """使用 Catbox 上傳圖片（無需 API key，備用）"""
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

        print(f"Catbox 上傳失敗: {response.status_code} - {response.text[:200]}")
    except Exception as e:
        print(f"Catbox 上傳異常: {e}")
    return None


def upload_image(image_path: str) -> str:
    """嘗試多個圖床上傳，返回第一個成功的 URL"""
    print(f"嘗試上傳圖片: {image_path}")

    url = upload_to_telegraph(image_path)
    if url:
        print(f"✅ Telegraph 上傳成功: {url}")
        return url

    print("→ 嘗試備用圖床 Catbox...")
    url = upload_to_catbox(image_path)
    if url:
        print(f"✅ Catbox 上傳成功: {url}")
        return url

    print("❌ 所有圖床上傳失敗")
    return None


def main():
    logger.info("=" * 50)
    logger.info("🚀 台股推薦機器人自動執行")
    logger.info("=" * 50)
    start_time = datetime.now()

    try:
        logger.info("\n📌 步驟 1: 設定 Google Drive 連線")
        drive_service = get_drive_service()

        logger.info("\n📌 步驟 2: 從 Google Drive 同步資料庫")
        sync_database_from_drive(drive_service)

        logger.info("\n📌 步驟 3: 建立資料庫")
        ensure_db()
        logger.debug(f"資料庫路徑: {DB_PATH}")

        logger.info("\n📌 步驟 4: 檢查並下載需要的數據")
        df_new = fetch_prices_yf(CODES, lookback_days=120)
        data_updated = False
        if not df_new.empty:
            upsert_prices(df_new)
            data_updated = True
            logger.info("✅ 資料庫已更新")
        else:
            logger.info("ℹ️  無需更新資料庫")

        logger.info("\n📌 步驟 5: 載入數據並篩選股票")
        hist = load_recent_prices(days=120)
        picks = pick_stocks(hist, top_k=PICKS_TOP_K)
        logger.debug(f"載入 {len(hist)} 筆歷史資料")
        logger.debug(f"篩選出 {len(picks)} 支符合條件的股票")

        logger.info("\n📌 步驟 6: 將股票分組")
        today_tpe = datetime.now(timezone(timedelta(hours=8))).date()
        today_weekday = today_tpe.weekday()  # 0=週一, 6=週日

        if picks.empty:
            group1 = pd.DataFrame()
            group2 = pd.DataFrame()
        else:
            group1 = picks[(picks["ma20_slope"] >= 0.5) & (picks["ma20_slope"] < 1)]
            group2 = picks[picks["ma20_slope"] < 0.5]

        logger.info(f"📈 好像蠻強的（斜率 0.5-1）：{len(group1)} 支")
        logger.info(f"📊 有機會噴 觀察一下（斜率 < 0.5）：{len(group2)} 支")

        logger.info("\n📌 步驟 7: 發送 LINE 訊息")

        # 檢查是否為週末（週六=5, 週日=6）
        if today_weekday >= 5:
            weekday_names = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
            logger.info(f"🗓️  今日為{weekday_names[today_weekday]} ({today_tpe})，股市休市，跳過發送訊息")
            logger.info("📴 週末不發送股票推薦訊息")
        else:
            # 平日發送訊息
            if group1.empty and group2.empty:
                msg = f"📉 {today_tpe}\n今日無符合條件之台股推薦。"
                logger.info(f"將發送的訊息:\n{msg}")
                try:
                    line_push_text(msg)
                    logger.info("✅ LINE 訊息發送成功！")
                except Exception as e:
                    logger.error(f"❌ LINE 訊息發送失敗: {e}")
            else:
                if not group1.empty:
                    logger.info("\n處理「好像蠻強的」組...")
                    lines = [f"💪 好像蠻強的 ({today_tpe})"]
                    lines.append("以下股票可以參考：\n")
                    for i, r in group1.iterrows():
                        stock_name = STOCK_NAMES.get(r.code, r.code)
                        lines.append(f"{r.code} {stock_name}")
                    msg1 = "\n".join(lines)
                    logger.info(f"訊息:\n{msg1}")

                    try:
                        line_push_text(msg1)
                        logger.info("✅ 好像蠻強的組訊息發送成功")
                    except Exception as e:
                        logger.error(f"❌ 好像蠻強的組訊息發送失敗: {e}")

                logger.info("\n生成並發送「好像蠻強的」組圖片")
                group1_codes = group1["code"].tolist()
                for batch_num in range(0, len(group1_codes), 6):
                    batch_codes = group1_codes[batch_num:batch_num + 6]
                    batch_display = ", ".join(batch_codes)
                    logger.info(f"正在處理好像蠻強的第 {batch_num//6 + 1} 組: {batch_display}")

                    chart_path = plot_stock_charts(batch_codes, hist)
                    if chart_path:
                        img_url = upload_image(chart_path)
                        if img_url:
                            try:
                                push_image(img_url, img_url)
                                logger.info(f"✅ 圖表已發送到 LINE")
                            except Exception as e:
                                logger.error(f"❌ LINE 發送失敗: {e}")
                            os.unlink(chart_path)
                        else:
                            logger.warning(f"❌ 圖床上傳失敗")
                    else:
                        logger.warning(f"❌ 圖表生成失敗")

                if not group2.empty:
                    logger.info("\n處理「有機會噴 觀察一下」組...")
                    lines = [f"👀 有機會噴 觀察一下 ({today_tpe})"]
                    lines.append("以下股票可以參考：\n")
                    for i, r in group2.iterrows():
                        stock_name = STOCK_NAMES.get(r.code, r.code)
                        lines.append(f"{r.code} {stock_name}")
                    msg2 = "\n".join(lines)
                    logger.info(f"訊息:\n{msg2}")

                    try:
                        line_push_text(msg2)
                        logger.info("✅ 有機會噴 觀察一下組訊息發送成功")
                    except Exception as e:
                        logger.error(f"❌ 有機會噴 觀察一下組訊息發送失敗: {e}")

                    logger.info("\n生成並發送「有機會噴 觀察一下」組圖片")
                    group2_codes = group2["code"].tolist()
                    for batch_num in range(0, len(group2_codes), 6):
                        batch_codes = group2_codes[batch_num:batch_num + 6]
                        batch_display = ", ".join(batch_codes)
                        logger.info(f"正在處理有機會噴 觀察一下第 {batch_num//6 + 1} 組: {batch_display}")

                        chart_path = plot_stock_charts(batch_codes, hist)
                        if chart_path:
                            img_url = upload_image(chart_path)
                            if img_url:
                                try:
                                    push_image(img_url, img_url)
                                    logger.info(f"✅ 圖表已發送到 LINE")
                                except Exception as e:
                                    logger.error(f"❌ LINE 發送失敗: {e}")
                                os.unlink(chart_path)
                            else:
                                logger.warning(f"❌ 圖床上傳失敗")
                        else:
                            logger.warning(f"❌ 圖表生成失敗")

        # 步驟 8: 同步資料庫到 Google Drive（如果有更新資料）
        if data_updated and drive_service:
            logger.info("\n📌 步驟 8: 同步資料庫到 Google Drive")
            sync_database_to_drive(drive_service)
        elif drive_service:
            logger.info("\n步驟 8: 資料無更新，跳過 Google Drive 同步")
        else:
            logger.info("\n步驟 8: Google Drive 服務不可用，跳過同步")

        # 任務完成
        end_time = datetime.now()
        execution_time = end_time - start_time
        logger.info("\n" + "=" * 50)
        logger.info(f"🎉 任務完成！執行時間: {execution_time}")
        logger.info("=" * 50)

    except Exception as e:
        logger.error(f"❌ 程式執行發生錯誤: {e}")
        if DEBUG_MODE:
            logger.debug(f"詳細錯誤: {str(e)}", exc_info=True)
        raise
    finally:
        if DEBUG_MODE:
            logger.debug("程式執行結束")


if __name__ == "__main__":
    main()