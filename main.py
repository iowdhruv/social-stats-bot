import os
import json
import gspread
import requests
import time
import isodate # You need to add 'isodate' to requirements.txt
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
    """Converts PT1M30S to 1:30"""
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
        # Fetch snippet (Title, Date) AND contentDetails (Duration) AND statistics
        res = youtube.videos().list(part="snippet,contentDetails,statistics", id=video_id).execute()
        if not res['items']: return None
        
        item = res['items'][0]
        return {
            'date': item['snippet']['publishedAt'][:10],
            'title': item['snippet']['title'],
            'length': parse_duration(item['contentDetails']['duration']),
            'views': int(item['statistics']['viewCount'])
        }
    except: return None

# --- INSTA CODE ---
def get_insta_data(media_id):
    """Fetches IG stats using Token"""
    if not media_id or len(str(media_id)) < 5: return None
    try:
        token = os.environ['INSTAGRAM_TOKEN']
        # I added 'print' here so we can see the secret data in the logs
        url = f"https://graph.facebook.com/v19.0/{media_id}?fields=id,media_type,like_count,comments_count,media_product_type&access_token={token}"
        
        r = requests.get(url)
        data = r.json()
        
        # --- DEBUG PRINT ---
        print(f"DEBUG DATA for {media_id}: {data}") 
        # -------------------

        if 'error' in data:
            print(f"IG Error: {data['error']['message']}")
            return None
            
        return {
            'date': data.get('timestamp', '')[:10],
            'title': data.get('caption', '')[:50].split('\n')[0],
            'views': int(data.get('like_count', 0)), 
            'comments': int(data.get('comments_count', 0))
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
        
        # Check Inputs
        yt_id = row[7].strip() if len(row) > 7 else ""
        ig_id = row[8].strip() if len(row) > 8 else ""
        
        # Check if Metadata exists (Col A = Date, Col B = Title)
        has_metadata = (row[0] != "" and row[1] != "")
        
        # --- YOUTUBE LOGIC ---
        if yt_id:
            yt_data = get_youtube_data(yt_id)
            if yt_data:
                # Always update Views (Col E / Index 5)
                cells_to_update.append(gspread.Cell(row_num, 5, yt_data['views']))
                
                # If metadata missing, fill it!
                if not has_metadata:
                    cells_to_update.append(gspread.Cell(row_num, 1, yt_data['date']))   # A
                    cells_to_update.append(gspread.Cell(row_num, 2, yt_data['title']))  # B
                    cells_to_update.append(gspread.Cell(row_num, 3, yt_data['length'])) # C
                    has_metadata = True # Prevent IG from overwriting if YT already did it
                
        # --- INSTAGRAM LOGIC ---
                if ig_id:
                    ig_data = get_insta_data(ig_id)
                    if ig_data:
                        # Always update Stats
                        cells_to_update.append(gspread.Cell(row_num, 4, ig_data['views']))    # D
                        cells_to_update.append(gspread.Cell(row_num, 6, ig_data['comments'])) # F
                        cells_to_update.append(gspread.Cell(row_num, 7, ig_data['shares']))   # G
                        
                # If metadata STILL missing (no YT), fill from IG
                    if not has_metadata:
                        cells_to_update.append(gspread.Cell(row_num, 1, ig_data['date']))
                        cells_to_update.append(gspread.Cell(row_num, 2, ig_data['title']))                
        # IG has no "Length", leave C blank
    
    time.sleep(0.1)

    if cells_to_update:
        print(f"Updating {len(cells_to_update)} cells...")
        sheet.update_cells(cells_to_update)
        print("Done.")
