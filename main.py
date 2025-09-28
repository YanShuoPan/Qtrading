import os
import requests
import sqlite3
from datetime import datetime, timedelta, timezone
import tempfile
import base64
import json
import io

import pandas as pd
import numpy as np
import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

load_dotenv()
LINE_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_USER_ID = os.environ["LINE_USER_ID"]

DATA_DIR = os.environ.get("DATA_DIR", "data")
DB_PATH = os.path.join(DATA_DIR, "taiex.sqlite")
GDRIVE_FOLDER_NAME = "stocks-autobot-data"
GDRIVE_DATA_FOLDER = "data"  # 在stocks-autobot-data下的子資料夾

# Google Drive Service Account setup
SCOPES = ['https://www.googleapis.com/auth/drive']

# Use environment variable for stock codes, fallback to comprehensive list
DEFAULT_CODES = [
    "2330", "2317", "2454", "2881", "2882", "2886", "2412", "2891", "2303", "1301",
    "1303", "2308", "2002", "2884", "2892", "2912", "2885", "1326", "2395", "2357",
    "3711", "2382", "1216", "2207", "6505", "2603", "2609", "2615", "3008", "2327",
    "2880", "2887", "5880", "2890", "3045", "4904", "5871", "2324", "2301", "4938",
    "2409", "3037", "2344", "2345", "6415", "3034", "2379", "3231", "2408", "3661",
    "3443", "2449", "2377", "6669", "2474", "1102", "2105", "2201", "2227", "6176",
    "9910", "2834", "2801", "2049", "2353", "2354", "2356", "3706", "5269", "6239",
    "6271", "3481", "4961", "2360", "2385", "2458", "3545", "8046", "2368", "2371",
    "2376", "6282", "4968", "3017", "2347", "2393", "6116", "8150", "2313", "2337",
    "6414", "2107", "2204", "2362", "2427", "5876", "9945", "2101", "2364", "3702"
]

CODES = os.environ.get("TWSE_CODES", ",".join(DEFAULT_CODES)).split(",")
PICKS_TOP_K = int(os.environ.get("TOP_K", "100"))

STOCK_NAMES = {
    "2330": "台積電", "2317": "鴻海", "2454": "聯發科", "2881": "富邦金", "2882": "國泰金",
    "2886": "兆豐金", "2412": "中華電", "2891": "中信金", "2303": "聯電", "1301": "台塑",
    "1303": "南亞", "2308": "台達電", "2002": "中鋼", "2884": "玉山金", "2892": "第一金",
    "2912": "統一超", "2885": "元大金", "1326": "台化", "2395": "研華", "2357": "華碩",
    "3711": "日月光投控", "2382": "廣達", "1216": "統一", "2207": "和泰車", "6505": "台塑化",
    "2603": "長榮", "2609": "陽明", "2615": "萬海", "3008": "大立光", "2327": "國巨*",
    "2880": "華南金", "2887": "台新新光金", "5880": "合庫金", "2890": "永豐金", "3045": "台灣大",
    "4904": "遠傳", "5871": "中租-KY", "2324": "仁寶", "2301": "光寶科", "4938": "和碩",
    "2409": "友達", "3037": "欣興", "2344": "華邦電", "2345": "智邦", "6415": "矽力*-KY",
    "3034": "聯詠", "2379": "瑞昱", "3231": "緯創", "2408": "南亞科", "3661": "世芯-KY",
    "3443": "創意", "2449": "京元電子", "2377": "微星", "6669": "緯穎", "2474": "可成",
    "1102": "亞泥", "2105": "正新", "2201": "裕隆", "2227": "裕日車", "6176": "瑞儀",
    "9910": "豐泰", "2834": "臺企銀", "2801": "彰銀", "2049": "上銀", "2353": "宏碁",
    "2354": "鴻準", "2356": "英業達", "3706": "神達", "5269": "祥碩", "6239": "力成",
    "6271": "同欣電", "3481": "群創", "4961": "天鈺", "2360": "致茂", "2385": "群光",
    "2458": "義隆", "3545": "敦泰", "8046": "南電", "2368": "金像電", "2371": "大同",
    "2376": "技嘉", "6282": "康舒", "4968": "立積", "3017": "奇鋐", "2347": "聯強",
    "2393": "億光", "6116": "彩晶", "8150": "南茂", "2313": "華通", "2337": "旺宏",
    "6414": "樺漢", "2107": "厚生", "2204": "中華", "2362": "藍天", "2427": "三商電",
    "5876": "上海商銀", "9945": "潤泰新", "2101": "南港", "2364": "倫飛", "3702": "大聯大"
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
    """建立 Google Drive API 服務（使用 Service Account）"""
    try:
        # 從環境變數讀取 Service Account JSON
        sa_json_str = os.environ.get("GDRIVE_SERVICE_ACCOUNT")
        if not sa_json_str:
            print("❌ 未設定 GDRIVE_SERVICE_ACCOUNT 環境變數，跳過 Google Drive 功能")
            return None

        sa_json = json.loads(sa_json_str)
        credentials = service_account.Credentials.from_service_account_info(sa_json, scopes=SCOPES)
        service = build('drive', 'v3', credentials=credentials)
        print("✅ Google Drive Service Account 認證成功")
        return service
    except Exception as e:
        print(f"❌ Google Drive 認證失敗: {e}")
        return None


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
        return False

    try:
        # 尋找檔案
        query = f"name='{file_name}' and '{folder_id}' in parents and trashed=false"
        results = service.files().list(q=query, fields='files(id, name)').execute()
        items = results.get('files', [])

        if not items:
            print(f"📁 Google Drive 中找不到檔案: {file_name}")
            return False

        file_id = items[0]['id']

        # 下載檔案
        request = service.files().get_media(fileId=file_id)
        file_buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(file_buffer, request)

        done = False
        while done is False:
            status, done = downloader.next_chunk()

        # 寫入本地檔案
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, 'wb') as f:
            f.write(file_buffer.getvalue())

        print(f"✅ 已從 Google Drive 下載: {file_name}")
        return True

    except Exception as e:
        print(f"❌ 下載檔案失敗: {e}")
        return False


def upload_file_to_drive(service, local_path, file_name, folder_id):
    """上傳檔案到 Google Drive"""
    if not service:
        return False

    try:
        # 檢查檔案是否已存在
        query = f"name='{file_name}' and '{folder_id}' in parents and trashed=false"
        results = service.files().list(q=query, fields='files(id, name)').execute()
        items = results.get('files', [])

        file_metadata = {'name': file_name, 'parents': [folder_id]}
        media = MediaFileUpload(local_path, resumable=True)

        if items:
            # 更新現有檔案
            file_id = items[0]['id']
            file = service.files().update(fileId=file_id, media_body=media).execute()
            print(f"✅ 已更新 Google Drive 檔案: {file_name}")
        else:
            # 建立新檔案
            file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            print(f"✅ 已上傳新檔案到 Google Drive: {file_name}")

        return True

    except Exception as e:
        print(f"❌ 上傳檔案失敗: {e}")
        return False


def setup_google_drive_folders(service):
    """設定 Google Drive 資料夾結構"""
    if not service:
        return None

    try:
        # 尋找或建立主資料夾 stocks-autobot-data
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

        return data_folder_id

    except Exception as e:
        print(f"❌ 設定 Google Drive 資料夾失敗: {e}")
        return None


def sync_database_from_drive(service):
    """從 Google Drive 同步資料庫到本地"""
    if not service:
        print("⚠️  跳過 Google Drive 下載（Service 不可用）")
        return False

    try:
        data_folder_id = setup_google_drive_folders(service)
        if not data_folder_id:
            return False

        # 下載 taiex.sqlite
        success = download_file_from_drive(service, "taiex.sqlite", data_folder_id, DB_PATH)
        return success

    except Exception as e:
        print(f"❌ 從 Google Drive 同步資料庫失敗: {e}")
        return False


def sync_database_to_drive(service):
    """上傳本地資料庫到 Google Drive"""
    if not service:
        print("⚠️  跳過 Google Drive 上傳（Service 不可用）")
        return False

    try:
        if not os.path.exists(DB_PATH):
            print(f"⚠️  本地資料庫不存在: {DB_PATH}")
            return False

        data_folder_id = setup_google_drive_folders(service)
        if not data_folder_id:
            return False

        # 上傳 taiex.sqlite
        success = upload_file_to_drive(service, DB_PATH, "taiex.sqlite", data_folder_id)
        return success

    except Exception as e:
        print(f"❌ 上傳資料庫到 Google Drive 失敗: {e}")
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
    codes = codes[:6]
    n_stocks = len(codes)
    if n_stocks == 0:
        return None

    plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'SimHei', 'Arial']
    plt.rcParams['axes.unicode_minus'] = False

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
    print("=== 台股推薦機器人自動執行 ===\n")

    print("步驟 1: 設定 Google Drive 連線")
    drive_service = get_drive_service()

    print("\n步驟 2: 從 Google Drive 同步資料庫")
    sync_database_from_drive(drive_service)

    print("\n步驟 3: 建立資料庫")
    ensure_db()

    print("\n步驟 4: 檢查並下載需要的數據")
    df_new = fetch_prices_yf(CODES, lookback_days=120)
    data_updated = False
    if not df_new.empty:
        upsert_prices(df_new)
        data_updated = True
        print("✅ 資料庫已更新")
    else:
        print("無需更新資料庫")

    print("\n步驟 5: 載入數據並篩選股票")
    hist = load_recent_prices(days=120)
    picks = pick_stocks(hist, top_k=PICKS_TOP_K)

    print("\n步驟 6: 將股票分組")
    today_tpe = datetime.now(timezone(timedelta(hours=8))).date()

    if picks.empty:
        group1 = pd.DataFrame()
        group2 = pd.DataFrame()
    else:
        group1 = picks[(picks["ma20_slope"] >= 0.5) & (picks["ma20_slope"] < 1)]
        group2 = picks[picks["ma20_slope"] < 0.5]

    print(f"好像蠻強的（斜率 0.5-1）：{len(group1)} 支")
    print(f"有機會噴 觀察一下（斜率 < 0.5）：{len(group2)} 支")

    print("\n步驟 7: 發送 LINE 訊息")

    if group1.empty and group2.empty:
        msg = f"📉 {today_tpe}\n今日無符合條件之台股推薦。"
        print(f"\n將發送的訊息:\n{msg}\n")
        try:
            line_push_text(msg)
            print("✅ LINE 訊息發送成功！")
        except Exception as e:
            print(f"❌ LINE 訊息發送失敗: {e}")
    else:
        if not group1.empty:
            print("\n處理「好像蠻強的」組...")
            lines = [f"💪 好像蠻強的 ({today_tpe})"]
            lines.append("以下股票可以參考：\n")
            for i, r in group1.iterrows():
                stock_name = STOCK_NAMES.get(r.code, r.code)
                lines.append(f"{r.code} {stock_name}")
            msg1 = "\n".join(lines)
            print(f"訊息:\n{msg1}\n")

            try:
                line_push_text(msg1)
                print("✅ 好像蠻強的組訊息發送成功")
            except Exception as e:
                print(f"❌ 好像蠻強的組訊息發送失敗: {e}")

            print("\n生成並發送「好像蠻強的」組圖片")
            group1_codes = group1["code"].tolist()
            for batch_num in range(0, len(group1_codes), 6):
                batch_codes = group1_codes[batch_num:batch_num + 6]
                batch_display = ", ".join(batch_codes)
                print(f"正在處理好像蠻強的第 {batch_num//6 + 1} 組: {batch_display}")

                chart_path = plot_stock_charts(batch_codes, hist)
                if chart_path:
                    img_url = upload_image(chart_path)
                    if img_url:
                        try:
                            push_image(img_url, img_url)
                            print(f"✅ 圖表已發送到 LINE")
                        except Exception as e:
                            print(f"❌ LINE 發送失敗: {e}")
                        os.unlink(chart_path)
                    else:
                        print(f"❌ 圖床上傳失敗")
                else:
                    print(f"❌ 圖表生成失敗")

        if not group2.empty:
            print("\n處理「有機會噴 觀察一下」組...")
            lines = [f"👀 有機會噴 觀察一下 ({today_tpe})"]
            lines.append("以下股票可以參考：\n")
            for i, r in group2.iterrows():
                stock_name = STOCK_NAMES.get(r.code, r.code)
                lines.append(f"{r.code} {stock_name}")
            msg2 = "\n".join(lines)
            print(f"訊息:\n{msg2}\n")

            try:
                line_push_text(msg2)
                print("✅ 有機會噴 觀察一下組訊息發送成功")
            except Exception as e:
                print(f"❌ 有機會噴 觀察一下組訊息發送失敗: {e}")

            print("\n生成並發送「有機會噴 觀察一下」組圖片")
            group2_codes = group2["code"].tolist()
            for batch_num in range(0, len(group2_codes), 6):
                batch_codes = group2_codes[batch_num:batch_num + 6]
                batch_display = ", ".join(batch_codes)
                print(f"正在處理有機會噴 觀察一下第 {batch_num//6 + 1} 組: {batch_display}")

                chart_path = plot_stock_charts(batch_codes, hist)
                if chart_path:
                    img_url = upload_image(chart_path)
                    if img_url:
                        try:
                            push_image(img_url, img_url)
                            print(f"✅ 圖表已發送到 LINE")
                        except Exception as e:
                            print(f"❌ LINE 發送失敗: {e}")
                        os.unlink(chart_path)
                    else:
                        print(f"❌ 圖床上傳失敗")
                else:
                    print(f"❌ 圖表生成失敗")

    # 步驟 8: 同步資料庫到 Google Drive（如果有更新資料）
    if data_updated and drive_service:
        print("\n步驟 8: 同步資料庫到 Google Drive")
        sync_database_to_drive(drive_service)
    elif drive_service:
        print("\n步驟 8: 資料無更新，跳過 Google Drive 同步")
    else:
        print("\n步驟 8: Google Drive 服務不可用，跳過同步")

    print("\n🎉 任務完成！")


if __name__ == "__main__":
    main()