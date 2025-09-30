"""
測試 Google Drive OAuth 認證
用來驗證 token 是否有效
"""
import os
import json
import sys
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

def test_token():
    """測試 token 是否有效"""

    # 從環境變數讀取
    token_json = os.environ.get('GDRIVE_TOKEN_JSON', '')
    client_id = os.environ.get('GDRIVE_CLIENT_ID', '')
    client_secret = os.environ.get('GDRIVE_CLIENT_SECRET', '')

    if not token_json:
        print("❌ GDRIVE_TOKEN_JSON 環境變數未設定")
        return False

    print(f"✓ Token JSON length: {len(token_json)}")
    print(f"✓ Client ID length: {len(client_id)}")
    print(f"✓ Client Secret length: {len(client_secret)}")
    print(f"✓ Token starts with: {token_json[:30]}...")

    try:
        # 解析 token JSON
        token_data = json.loads(token_json)
        print(f"✓ Token JSON 解析成功")
        print(f"  - Has access_token: {'access_token' in token_data}")
        print(f"  - Has refresh_token: {'refresh_token' in token_data}")
        print(f"  - Has token_type: {'token_type' in token_data}")

        if 'refresh_token' not in token_data:
            print("⚠️ 警告：Token 中沒有 refresh_token，token 過期後將無法更新")

        # 建立 credentials
        creds = Credentials(
            token=token_data.get('access_token'),
            refresh_token=token_data.get('refresh_token'),
            token_uri='https://oauth2.googleapis.com/token',
            client_id=client_id if client_id else None,
            client_secret=client_secret if client_secret else None
        )

        print(f"✓ Credentials 建立成功")

        # 測試 Google Drive API
        print("\n測試 Google Drive API 連接...")
        service = build('drive', 'v3', credentials=creds)

        # 嘗試列出檔案（限制 1 個）
        results = service.files().list(pageSize=1, fields="files(id, name)").execute()
        files = results.get('files', [])

        print(f"✅ Google Drive API 連接成功！")
        if files:
            print(f"   找到檔案: {files[0]['name']}")
        else:
            print(f"   Drive 中沒有檔案或權限不足")

        return True

    except json.JSONDecodeError as e:
        print(f"❌ Token JSON 格式錯誤: {e}")
        print(f"   請確認 GDRIVE_TOKEN_JSON 是有效的 JSON 格式")
        return False

    except HttpError as e:
        print(f"❌ Google Drive API 錯誤: {e}")
        if e.resp.status == 401:
            print(f"   可能原因：token 已過期或無效")
        elif e.resp.status == 403:
            print(f"   可能原因：權限不足或 API 未啟用")
        return False

    except Exception as e:
        print(f"❌ 發生錯誤: {type(e).__name__}: {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("Google Drive OAuth Token 測試")
    print("=" * 60)

    success = test_token()

    print("\n" + "=" * 60)
    if success:
        print("✅ 測試通過！Token 可以正常使用")
        sys.exit(0)
    else:
        print("❌ 測試失敗！請檢查 token 設定")
        sys.exit(1)