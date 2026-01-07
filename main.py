import os
import json
import gspread
import requests
import time
import isodate 
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# --- COLUMN CONFIG (1-Based Index) ---
COL_DATE = 1        # A
COL_TITLE = 2       # B
COL_LENGTH = 3      # C
COL_IG_VIEWS = 4    # D
COL_YT_VIEWS = 5    # E
COL_IG_COMMENTS = 6 # F
COL_IG_SHARES = 7   # G
COL_YT_ID = 8       # H
COL_IG_ID = 9       # I

# --- SETUP ---
json_creds = json.loads(os.environ['GOOGLE_SHEETS_JSON'])
SCOPE = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_info(json_creds, scopes=SCOPE)
client = gspread.authorize(creds)
sheet = client.open_by_key(os.environ['SHEET_KEY']).sheet1 

def parse_duration(iso_duration):
    try:
        dur = isodate.parse_duration(iso_duration)
        total_seconds = int(dur.total_seconds())
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes}:{seconds:02d}"
    except: return ""

def get_youtube_data(video_id):
    if not video_id or len(str(video_id)) < 5: return None
    try:
        api_key = os.environ['YOUTUBE_API_KEY']
        youtube = build('youtube', 'v3', developerKey=api_key)
        res = youtube.videos().list(part="snippet,contentDetails,statistics", id=video_id).execute()
        if not res['items']: return None
        item = res['items'][0]
        stats = item['statistics']
        return {
            'date': item['snippet']['publishedAt'][:10],
            'title': item['snippet']['title'],
            'length': parse_duration(item['contentDetails']['duration']),
            'views': int(stats.get('viewCount', 0))
        }
    except: return None

def get_insta_data(media_id):
    if not media_id or len(str(media_id)) < 5: return None
    token = os.environ['INSTAGRAM_TOKEN']
    url = f"https://graph.facebook.com/v22.0/{media_id}?fields=timestamp,caption,comments_count,media_product_type&access_token={token}"
    
    try:
        r = requests.get(url).json()
        if 'error' in r:
            print(f"IG Error: {r['error']['message']}")
            return None

        # Insights (Views/Plays)
        final_views = 0
        try:
            r_ins = requests.get(f"https://graph.facebook.com/v22.0/{media_id}/insights?metric=views&access_token={token}").json()
            if 'data' in r_ins:
                 final_views = int(r_ins['data'][0]['values'][0]['value'])
            elif 'error' in r_ins:
                 r_retry = requests.get(f"https://graph.facebook.com/v22.0/{media_id}/insights?metric=plays&access_token={token}").json()
                 if 'data' in r_retry:
                     final_views = int(r_retry['data'][0]['values'][0]['value'])
        except: pass

        return {
            'date': r.get('timestamp', '')[:10],
            'title': r.get('caption', '')[:50].split('\n')[0],
            'views': final_views,
            'comments': int(r.get('comments_count', 0))
        }
    except Exception as e:
        print(f"IG Exception: {e}")
        return None

if __name__ == "__main__":
    print("Reading Sheet...")
    all_data = sheet.get_all_values()
    cells_to_update = []
    
    for i in range(2, len(all_data)):
        row_num = i + 1
        row = all_data[i]
        
        yt_id = row[COL_YT_ID - 1].strip() if len(row) > (COL_YT_ID - 1) else ""
        ig_id = row[COL_IG_ID - 1].strip() if len(row) > (COL_IG_ID - 1) else ""
        
        # --- YOUTUBE LOGIC ---
        if yt_id:
            yt_data = get_youtube_data(yt_id)
            if yt_data:
                cells_to_update.append(gspread.Cell(row_num, COL_YT_VIEWS, yt_data['views']))
                
                # FORCE OVERWRITE METADATA
                # Writing to A, B, C regardless of what is there
                cells_to_update.append(gspread.Cell(row_num, COL_DATE, yt_data['date']))
                cells_to_update.append(gspread.Cell(row_num, COL_TITLE, yt_data['title']))
                cells_to_update.append(gspread.Cell(row_num, COL_LENGTH, yt_data['length']))

        # --- INSTAGRAM LOGIC ---
        if ig_id:
            ig_data = get_insta_data(ig_id)
            if ig_data:
                cells_to_update.append(gspread.Cell(row_num, COL_IG_VIEWS, ig_data['views']))
                cells_to_update.append(gspread.Cell(row_num, COL_IG_COMMENTS, ig_data['comments']))
                
                # METADATA: Only write if YT is missing
                if not yt_id:
                    cells_to_update.append(gspread.Cell(row_num, COL_DATE, ig_data['date']))
                    cells_to_update.append(gspread.Cell(row_num, COL_TITLE, ig_data['title']))
        
        time.sleep(0.2)

    if cells_to_update:
        print(f"Updating {len(cells_to_update)} cells...")
        sheet.update_cells(cells_to_update)
        print("Success!")
