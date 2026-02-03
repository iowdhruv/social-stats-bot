import os
import json
import gspread
import requests
import re
from google.oauth2.service_account import Credentials

# --- CONFIG ---
COL_YT_ID = 13  # Column M
COL_IG_ID = 14  # Column N
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
    # Extract ID from various YT url formats
    match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11})', text)
    if match: return match.group(1)
    if len(text) == 11 and "http" not in text: return text
    return text 

def get_ig_id_map():
    print("Fetching Instagram Media Map (All Posts)...")
    
    # 1. Find the Page with Instagram
    user_url = f"https://graph.facebook.com/v22.0/me/accounts?fields=name,instagram_business_account&access_token={insta_token}"
    user_res = requests.get(user_url).json()
    
    if 'data' not in user_res:
        print("❌ Error: No Pages found.")
        return {}

    ig_biz_id = None
    for page in user_res['data']:
        if 'instagram_business_account' in page:
            ig_biz_id = page['instagram_business_account']['id']
            print(f"✅ Found Page: {page.get('name')} -> IG ID: {ig_biz_id}")
            break

    if not ig_biz_id:
        print("❌ Error: No Instagram linked to any page.")
        return {}

    # 2. Fetch Media (With Pagination Loop)
    # We increase limit to 100 (API max) to reduce number of requests
    url = f"https://graph.facebook.com/v22.0/{ig_biz_id}/media?fields=shortcode,id&limit=100&access_token={insta_token}"
    id_map = {}
    page_count = 0
    
    while url:
        try:
            res = requests.get(url).json()
            
            if 'error' in res:
                print(f"❌ API Error: {res['error']['message']}")
                break
                
            items = res.get('data', [])
            if not items:
                break
                
            # Add this batch to our map
            for item in items:
                id_map[item['shortcode']] = item['id']
            
            page_count += 1
            print(f"   - Page {page_count}: Indexed {len(items)} posts...")

            # Check if there is a next page
            if 'paging' in res and 'next' in res['paging']:
                url = res['paging']['next']
            else:
                url = None # Stop loop
                
        except Exception as e:
            print(f"❌ Loop Exception: {e}")
            break
        
    print(f"✅ Finished! Indexed Total: {len(id_map)} posts.")
    return id_map

def extract_ig_shortcode(text):
    if not text: return ""
    # Matches /p/CODE, /reel/CODE, or raw CODE
    match = re.search(r'(?:p\/|reel\/)([A-Za-z0-9_-]+)', text)
    if match: return match.group(1)
    if "http" not in text and len(text) < 40: return text.strip()
    return text

# --- MAIN LOGIC ---
if __name__ == "__main__":
    ig_map = get_ig_id_map()
    all_values = sheet.get_all_values()
    updates = []
    
    print("\nScanning Sheet for messy URLs...")
    # Loop from Row 3 (index 2)
    for i in range(2, len(all_values)):
        row_num = i + 1
        row = all_values[i]
        
        # Safe Get
        current_yt = row[COL_YT_ID - 1].strip() if len(row) > (COL_YT_ID - 1) else ""
        current_ig = row[COL_IG_ID - 1].strip() if len(row) > (COL_IG_ID - 1) else ""
        
        # --- YT FIX ---
        clean_yt = extract_yt_id(current_yt)
        if clean_yt != current_yt and clean_yt != "":
            print(f"Row {row_num}: Cleaned YT Link -> {clean_yt}")
            updates.append(gspread.Cell(row_num, COL_YT_ID, clean_yt))
            
        # --- IG FIX ---
        shortcode = extract_ig_shortcode(current_ig)
        # If it looks like a shortcode (not a long number), try to swap it
        if shortcode and (not shortcode.isdigit() or len(shortcode) < 15):
            if shortcode in ig_map:
                official_id = ig_map[shortcode]
                if official_id != current_ig:
                    print(f"Row {row_num}: Swapped IG Link/Code '{shortcode}' -> ID {official_id}")
                    updates.append(gspread.Cell(row_num, COL_IG_ID, official_id))
            else:
                if current_ig and "http" in current_ig:
                     print(f"⚠️ Row {row_num}: IG Link '{shortcode}' not found in recent API fetch.")

    if updates:
        print(f"\nWriting {len(updates)} fixes...")
        sheet.update_cells(updates)
        print("✅ Done!")
    else:
        print("\n✅ Sheet is already clean.")
