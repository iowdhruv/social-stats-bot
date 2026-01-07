import os
import json
import gspread
import requests
import time
import isodate 
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# --- SETUP ---
json_creds = json.loads(os.environ['GOOGLE_SHEETS_JSON'])
SCOPE = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_info(json_creds, scopes=SCOPE)
client = gspread.authorize(creds)
sheet = client.open_by_key(os.environ['SHEET_KEY']).sheet1 

# --- HELPERS ---
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
            'comments': int(stats.get('commentCount', 0))
        }
    except: return None

def get_insta_data(media_id):
    if not media_id or len(str(media_id)) < 5: return None
    token = os.environ['INSTAGRAM_TOKEN']
    
    # 1. Basic Info (Caption, Date, Comments)
    url = f"https://graph.facebook.com/v22.0/{media_id}?fields=timestamp,caption,comments_count,media_product_type&access_token={token}"
    
    try:
        r = requests.get(url).json()
        if 'error' in r:
            print(f"IG Error: {r['error']['message']}")
            return None

        # 2. Insights: Ask for 'views' AND 'plays'
        # Some accounts have migrated to 'views', some are stuck on 'plays'
        insights_url = f"https://graph.facebook.com/v22.0/{media_id}/insights?metric=views,plays&access_token={token}"
        
        final_views = 0
        
        try:
            r_ins = requests.get(insights_url).json()
            
            # Print debug to see what we actually get
            if 'data' in r_ins:
                stats = {item['name']: int(item['values'][0]['value']) for item in r_ins['data']}
                print(f"🔍 Stats for {media_id}: {stats}")
                
                # Priority: Views > Plays
                if stats.get('views', 0) > 0:
                    final_views = stats['views']
                elif stats.get('plays', 0) > 0:
                    final_views = stats['plays']
            else:
                # If requesting BOTH fails (e.g. one metric is invalid), try just 'plays'
                # This handles the error "Metric views not supported"
                if 'error' in r_ins:
                     print(f"⚠️ specific metric error: {r_ins['error']['message']}")
                     # Retry with just plays
                     r_retry = requests.get(f"https://graph.facebook.com/v22.0/{media_id}/insights?metric=plays&access_token={token}").json()
                     if 'data' in r_retry:
                         final_views = int(r_retry['data'][0]['values'][0]['value'])
                         print(f"✅ Retry Success: Found {final_views} plays")

        except Exception as e:
            print(f"Insights Error: {e}")

        return {
            'date': r.get('timestamp', '')[:10],
            'title': r.get('caption', '')[:50].split('\n')[0],
            'views': final_views, # 0 if no views/plays found
            'comments': int(r.get('comments_count', 0))
        }
    except Exception as e:
        print(f"IG Exception: {e}")
        return None

# --- MAIN LOOP ---
if __name__ == "__main__":
    print("Reading Sheet...")
    all_data = sheet.get_all_values()
    cells_to_update = []
    
    for i in range(2, len(all_data)):
        row_num = i + 1
        row = all_data[i]
        
        yt_id = row[7].strip() if len(row) > 7 else ""
        ig_id = row[8].strip() if len(row) > 8 else ""
        has_metadata = (row[0] != "" and row[1] != "")
        
        # YT
        if yt_id:
            yt_data = get_youtube_data(yt_id)
            if yt_data:
                cells_to_update.append(gspread.Cell(row_num, 5, yt_data['views']))
                cells_to_update.append(gspread.Cell(row_num, 6, yt_data['comments']))
                if not has_metadata:
                    cells_to_update.append(gspread.Cell(row_num, 1, yt_data['date']))
                    cells_to_update.append(gspread.Cell(row_num, 2, yt_data['title']))
                    cells_to_update.append(gspread.Cell(row_num, 3, yt_data['length']))
                    has_metadata = True 

        # IG
        if ig_id:
            ig_data = get_insta_data(ig_id)
            if ig_data:
                # Only write stats if YT is missing
                if not yt_id:
                    cells_to_update.append(gspread.Cell(row_num, 5, ig_data['views']))
                    cells_to_update.append(gspread.Cell(row_num, 6, ig_data['comments']))
                
                # Metadata
                if not has_metadata:
                    cells_to_update.append(gspread.Cell(row_num, 1, ig_data['date']))
                    cells_to_update.append(gspread.Cell(row_num, 2, ig_data['title']))
                    has_metadata = True
        
        time.sleep(0.2)

    if cells_to_update:
        print(f"Updating {len(cells_to_update)} cells...")
        sheet.update_cells(cells_to_update)
        print("Success!")
