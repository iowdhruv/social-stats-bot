import os
import json
import gspread
import requests
import re
from google.oauth2.service_account import Credentials

# --- CONFIG ---
# Instagram fetch limit (increase if you have older posts in the sheet)
IG_FETCH_LIMIT = 50 

# --- SETUP ---
print("Authenticating...")
json_creds = json.loads(os.environ['GOOGLE_SHEETS_JSON'])
SCOPE = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_info(json_creds, scopes=SCOPE)
client = gspread.authorize(creds)
sheet = client.open_by_key(os.environ['SHEET_KEY']).sheet1
insta_token = os.environ['INSTAGRAM_TOKEN']

# --- HELPER FUNCTIONS ---

def extract_yt_id(text):
    """Extracts 11-char ID from YT URL or returns text if already ID"""
    if not text: return ""
    # Regex for standard v=ID or short youtu.be/ID
    match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11})', text)
    if match:
        return match.group(1)
    # If it looks like a raw ID already, return it
    if len(text) == 11 and "http" not in text:
        return text
    return text # Return original if unsure

def get_ig_id_map():
    """Fetches recent IG posts and creates a dictionary: {shortcode: media_id}"""
    print("Fetching Instagram Media Map...")
    
    # 1. Get IG Business ID
    user_url = f"https://graph.facebook.com/v19.0/me/accounts?fields=instagram_business_account&access_token={insta_token}"
    user_res = requests.get(user_url).json()
    
    try:
        ig_biz_id = user_res['data'][0]['instagram_business_account']['id']
    except (KeyError, IndexError):
        print("❌ Error: Could not find Instagram Business Account ID. Check permissions.")
        return {}

    # 2. Get Media List
    media_url = f"https://graph.facebook.com/v19.0/{ig_biz_id}/media?fields=shortcode,id&limit={IG_FETCH_LIMIT}&access_token={insta_token}"
    media_res = requests.get(media_url).json()
    
    id_map = {}
    for item in media_res.get('data', []):
        id_map[item['shortcode']] = item['id']
        
    print(f"✅ Found {len(id_map)} recent Instagram posts.")
    return id_map

def extract_ig_shortcode(text):
    """Extracts shortcode from URL or returns raw text"""
    if not text: return ""
    # Matches /p/CODE, /reel/CODE, or raw CODE
    match = re.search(r'(?:p\/|reel\/)([A-Za-z0-9_-]+)', text)
    if match:
        return match.group(1)
    # If no http/www, assume it is the shortcode
    if "http" not in text and len(text) < 20:
        return text.strip()
    return text

# --- MAIN LOGIC ---
if __name__ == "__main__":
    # 1. Prepare Data
    ig_map = get_ig_id_map()
    all_values = sheet.get_all_values()
    updates = []
    
    print("\nScanning Sheet for messy URLs...")
    
    # Start loop from Row 3 (Index 2)
    for i in range(2, len(all_values)):
        row_num = i + 1
        row = all_values[i]
        
        # Get current cell values (safely)
        current_yt = row[7].strip() if len(row) > 7 else ""
        current_ig = row[8].strip() if len(row) > 8 else ""
        
        # --- YOUTUBE FIX ---
        clean_yt = extract_yt_id(current_yt)
        if clean_yt != current_yt:
            print(f"Row {row_num}: Converting YT URL -> {clean_yt}")
            updates.append(gspread.Cell(row_num, 8, clean_yt)) # Col H is index 8 (1-based)
            
        # --- INSTAGRAM FIX ---
        # 1. Extract shortcode (e.g. from URL)
        shortcode = extract_ig_shortcode(current_ig)
        
        # 2. Check if it is already a long numeric ID (ignore if so)
        if not shortcode.isdigit() or len(shortcode) < 15:
            # 3. Lookup the official ID in our map
            if shortcode in ig_map:
                official_id = ig_map[shortcode]
                if official_id != current_ig:
                    print(f"Row {row_num}: Converting IG Shortcode {shortcode} -> {official_id}")
                    updates.append(gspread.Cell(row_num, 9, official_id)) # Col I is index 9 (1-based)
            else:
                if current_ig:
                    print(f"⚠️ Row {row_num}: Could not find Official ID for IG '{shortcode}' (Post might be too old or map failed)")

    # --- BATCH UPDATE ---
    if updates:
        print(f"\nWriting {len(updates)} fixes to Google Sheet...")
        sheet.update_cells(updates)
        print("✅ Sheet fixed!")
    else:
        print("\n✅ Sheet is already clean.")
