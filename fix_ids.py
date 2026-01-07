import os
import json
import gspread
import requests
import re
from google.oauth2.service_account import Credentials

# --- CONFIG ---
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
    if not text: return ""
    match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11})', text)
    if match: return match.group(1)
    if len(text) == 11 and "http" not in text: return text
    return text 

def get_ig_id_map():
    print("Fetching Instagram Media Map...")
    
    # 1. Get ALL Pages and look for the one with Instagram
    # We ask for the Page Name too, so the debug log is readable
    user_url = f"https://graph.facebook.com/v19.0/me/accounts?fields=name,instagram_business_account&access_token={insta_token}"
    user_res = requests.get(user_url).json()
    
    if 'error' in user_res:
        print(f"❌ API Error: {user_res['error']['message']}")
        return {}

    if 'data' not in user_res or not user_res['data']:
        print("❌ Error: No Facebook Pages found for this user token.")
        return {}

    ig_biz_id = None
    
    # Loop through ALL pages to find the connected one
    print(f"Found {len(user_res['data'])} Page(s). Scanning for Instagram link...")
    
    for page in user_res['data']:
        page_name = page.get('name', 'Unknown')
        if 'instagram_business_account' in page:
            ig_biz_id = page['instagram_business_account']['id']
            print(f"✅ Success! Found linked Instagram on page: '{page_name}' (ID: {ig_biz_id})")
            break # Stop looking, we found it
        else:
            print(f"   - Page '{page_name}' has NO Instagram linked.")

    if not ig_biz_id:
        print("❌ Error: None of the pages have an Instagram Business Account linked.")
        return {}

    # 2. Get Media List using that ID
    media_url = f"https://graph.facebook.com/v19.0/{ig_biz_id}/media?fields=shortcode,id&limit={IG_FETCH_LIMIT}&access_token={insta_token}"
    media_res = requests.get(media_url).json()
    
    id_map = {}
    for item in media_res.get('data', []):
        id_map[item['shortcode']] = item['id']
        
    print(f"✅ Indexed {len(id_map)} recent Instagram posts.")
    return id_map

def extract_ig_shortcode(text):
    if not text: return ""
    match = re.search(r'(?:p\/|reel\/)([A-Za-z0-9_-]+)', text)
    if match: return match.group(1)
    if "http" not in text and len(text) < 30: return text.strip()
    return text

# --- MAIN LOGIC ---
if __name__ == "__main__":
    ig_map = get_ig_id_map()
    
    # If map is empty, stop here to avoid erasing data
    if not ig_map:
        print("⚠️ Skipping Sheet Update because IG Map failed.")
        exit(1)

    all_values = sheet.get_all_values()
    updates = []
    
    print("\nScanning Sheet for messy URLs...")
    for i in range(2, len(all_values)):
        row_num = i + 1
        row = all_values[i]
        
        current_yt = row[7].strip() if len(row) > 7 else ""
        current_ig = row[8].strip() if len(row) > 8 else ""
        
        # YT Fix
        clean_yt = extract_yt_id(current_yt)
        if clean_yt != current_yt:
            print(f"Row {row_num}: Fix YT -> {clean_yt}")
            updates.append(gspread.Cell(row_num, 8, clean_yt))
            
        # IG Fix
        shortcode = extract_ig_shortcode(current_ig)
        if not shortcode.isdigit() or len(shortcode) < 15:
            if shortcode in ig_map:
                official_id = ig_map[shortcode]
                if official_id != current_ig:
                    print(f"Row {row_num}: Fix IG {shortcode} -> {official_id}")
                    updates.append(gspread.Cell(row_num, 9, official_id))
            else:
                if current_ig:
                    print(f"⚠️ Row {row_num}: IG Post '{shortcode}' not found in recent fetch.")

    if updates:
        print(f"\nWriting {len(updates)} fixes...")
        sheet.update_cells(updates)
        print("✅ Done!")
    else:
        print("\n✅ Sheet is clean.")
