import os
import json
import gspread
import requests
import time
import isodate 
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# --- COLUMN CONFIG (1-Based Index) ---
COL_DATE = 1          # A
COL_TITLE = 2         # B
COL_LENGTH = 3        # C
COL_IG_VIEWS = 4      # D
COL_YT_VIEWS = 5      # E
COL_IG_LIKES = 6      # F
COL_YT_LIKES = 7      # G
COL_IG_COMMENTS = 8   # H
COL_YT_COMMENTS = 9   # I
COL_IG_SHARES = 10    # J
COL_IG_SAVES = 11     # K
COL_IG_REACH = 12     # L
COL_YT_ID = 13        # M
COL_IG_ID = 14        # N

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
            'views': int(stats.get('viewCount', 0)),
            'likes': int(stats.get('likeCount', 0)),
            'comments': int(stats.get('commentCount', 0))
        }
    except: return None

def get_insta_data(media_id):
    if not media_id or len(str(media_id)) < 5: return None
    token = os.environ['INSTAGRAM_TOKEN']
    
    # 1. Basic Info
    url = f"https://graph.facebook.com/v22.0/{media_id}?fields=timestamp,caption,comments_count,like_count,media_product_type&access_token={token}"
    
    try:
        r = requests.get(url).json()
        if 'error' in r:
            print(f"IG Error: {r['error']['message']}")
            return None

        # 2. Insights
        # REMOVED 'plays' because it crashes v22 calls
        # 'views' covers Reels Plays now. 'impressions' covers Photos.
        
        final_views = 0
        reach = 0
        saves = 0
        
        # Strategy: Try 'views' (Video/Reel standard). If it fails, try 'impressions' (Photo standard).
        metrics_video = "views,reach,saved"
        metrics_photo = "impressions,reach,saved"
        
        # Determine likely type to choose metric
        is_video = r.get('media_product_type') == 'REELS' or r.get('media_type') == 'VIDEO'
        
        metrics_to_use = metrics_video if is_video else metrics_photo
        
        insights_url = f"https://graph.facebook.com/v22.0/{media_id}/insights?metric={metrics_to_use}&access_token={token}"
        
        try:
            r_ins = requests.get(insights_url).json()
            
            # Debug Print (Check logs if still 0)
            # print(f"DEBUG INSIGHTS for {media_id}: {r_ins}")

            if 'data' in r_ins:
                stats = {item['name']: int(item['values'][0]['value']) for item in r_ins['data']}
                
                # Parse Views/Impressions
                if 'views' in stats: final_views = stats['views']
                elif 'impressions' in stats: final_views = stats['impressions']
                
                # Parse Reach/Saves
                reach = stats.get('reach', 0)
                saves = stats.get('saved', 0)
            
            elif 'error' in r_ins:
                # Fallback: If 'views' failed for some reason, try the photo metric 'impressions' just in case
                if is_video:
                    # print("Video views failed, retrying with impressions...")
                    r_retry = requests.get(f"https://graph.facebook.com/v22.0/{media_id}/insights?metric={metrics_photo}&access_token={token}").json()
                    if 'data' in r_retry:
                        stats = {item['name']: int(item['values'][0]['value']) for item in r_retry['data']}
                        final_views = stats.get('impressions', 0)
                        reach = stats.get('reach', 0)
                        saves = stats.get('saved', 0)

        except Exception as e:
            print(f"IG Insights Logic Error: {e}")

        return {
            'date': r.get('timestamp', '')[:10],
            'title': r.get('caption', '')[:50].split('\n')[0],
            'views': final_views,
            'comments': int(r.get('comments_count', 0)),
            'likes': int(r.get('like_count', 0)),
            'reach': reach,
            'saves': saves
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
        
        # --- YT ---
        if yt_id:
            yt_data = get_youtube_data(yt_id)
            if yt_data:
                cells_to_update.append(gspread.Cell(row_num, COL_YT_VIEWS, yt_data['views']))
                cells_to_update.append(gspread.Cell(row_num, COL_YT_LIKES, yt_data['likes']))
                cells_to_update.append(gspread.Cell(row_num, COL_YT_COMMENTS, yt_data['comments']))
                cells_to_update.append(gspread.Cell(row_num, COL_DATE, yt_data['date']))
                cells_to_update.append(gspread.Cell(row_num, COL_TITLE, yt_data['title']))
                cells_to_update.append(gspread.Cell(row_num, COL_LENGTH, yt_data['length']))

        # --- IG ---
        if ig_id:
            ig_data = get_insta_data(ig_id)
            if ig_data:
                cells_to_update.append(gspread.Cell(row_num, COL_IG_VIEWS, ig_data['views']))
                cells_to_update.append(gspread.Cell(row_num, COL_IG_LIKES, ig_data['likes']))
                cells_to_update.append(gspread.Cell(row_num, COL_IG_COMMENTS, ig_data['comments']))
                cells_to_update.append(gspread.Cell(row_num, COL_IG_SAVES, ig_data['saves']))
                cells_to_update.append(gspread.Cell(row_num, COL_IG_REACH, ig_data['reach']))
                
                if not yt_id:
                    cells_to_update.append(gspread.Cell(row_num, COL_DATE, ig_data['date']))
                    cells_to_update.append(gspread.Cell(row_num, COL_TITLE, ig_data['title']))
        
        time.sleep(0.2)

    if cells_to_update:
        print(f"Updating {len(cells_to_update)} cells...")
        sheet.update_cells(cells_to_update)
        print("Success!")
