import os
import json
import gspread
import requests
import time
import isodate 
from datetime import datetime, timedelta, timezone
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# --- COLUMN CONFIG (1-Based Index) ---
COL_DATE = 1          # A
COL_TITLE = 2         # B
COL_LENGTH = 3        # C
COL_IG_VIEWS = 4      # D
COL_FB_VIEWS = 5      # E
COL_YT_VIEWS = 6      # F
COL_IG_LIKES = 7      # G
COL_FB_LIKES = 8      # H
COL_YT_LIKES = 9      # I
COL_IG_COMMENTS = 10  # J
COL_FB_COMMENTS = 11  # K
COL_YT_COMMENTS = 12  # L
COL_IG_SHARES = 13    # M
COL_FB_SHARES = 14    # N
COL_IG_SAVES = 15     # O
COL_IG_REACH = 16     # P
COL_FB_REACH = 17     # Q
COL_YT_ID = 18        # R
COL_IG_ID = 19        # S
COL_FB_ID = 20        # T

# --- GLOBAL STATS CONFIG ---
CELL_IG_FOLLOWERS = "W4"
CELL_FB_FOLLOWERS = "Z4"
CELL_YT_SUBS = "AC4"

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
        # --- New date logic --- #
        utc_dt = datetime.strptime(item['snippet']['publishedAt'], "%Y-%m-%dT%H:%M:%SZ")
        ist_date = (utc_dt + timedelta(hours=5, minutes=30)).strftime('%Y-%m-%d')
        # ----------------------
        
        return {
            'date': ist_date,
            'title': item['snippet']['title'],
            'length': parse_duration(item['contentDetails']['duration']),
            'views': int(stats.get('viewCount', 0)),
            'likes': int(stats.get('likeCount', 0)),
            'comments': int(stats.get('commentCount', 0)),
            'channel_id': item['snippet']['channelId'] # Grab ID for global stats later
        }
    except: return None


def get_fb_page_token_and_id():
    """Exchanges User Token for Page Access Token dynamically"""
    token = os.environ['INSTAGRAM_TOKEN']
    url = f"https://graph.facebook.com/v22.0/me/accounts?fields=id,access_token,instagram_business_account&access_token={token}"
    try:
        res = requests.get(url).json()
        if 'data' in res and len(res['data']) > 0:
            for page in res['data']:
                if 'instagram_business_account' in page:
                    return page['access_token'], page['id']
            return res['data'][0]['access_token'], res['data'][0]['id']
    except Exception as e:
        print(f"Error fetching Page Token: {e}")
    return None, None

def get_facebook_data(post_id, page_token, page_id=None):
    if not post_id or len(str(post_id)) < 5 or not page_token: return None
    
    user_token = os.environ['INSTAGRAM_TOKEN']
    tokens_to_try = [page_token, user_token]
    
    r = None
    used_token = None
    is_video_node = False
    last_error = None
    
    # 1. Fetch Node Data with Tiered Fallbacks
    for token in tokens_to_try:
        # Tier 1: Standard Post query
        url = (
            f"https://graph.facebook.com/v26.0/{post_id}"
            f"?fields=created_time,message,comments.summary(true),likes.summary(true),shares,permalink_url,from"
            f"&access_token={token}"
        )
        try:
            res = requests.get(url).json()
            
            # If standard post query fails with #100 or #200, treat as Video / Reel node
            if 'error' in res:
                last_error = res['error']
                is_video_node = True
                
                # Tier 2: Video/Reel node with engagement fields
                url = (
                    f"https://graph.facebook.com/v26.0/{post_id}"
                    f"?fields=created_time,description,title,views,comments.summary(true),likes.summary(true),permalink_url"
                    f"&access_token={token}"
                )
                res = requests.get(url).json()
                
                # Tier 3: If Tier 2 fails with #200 (common on cross-posted Reels due to engagement edges), query clean media fields
                if 'error' in res:
                    last_error = res['error']
                    url = (
                        f"https://graph.facebook.com/v26.0/{post_id}"
                        f"?fields=created_time,description,title,views,permalink_url"
                        f"&access_token={token}"
                    )
                    res = requests.get(url).json()
                    
                    # Tier 4: Minimal metadata fallback
                    if 'error' in res:
                        last_error = res['error']
                        url = (
                            f"https://graph.facebook.com/v26.0/{post_id}"
                            f"?fields=created_time,description,permalink_url"
                            f"&access_token={token}"
                        )
                        res = requests.get(url).json()
                        if 'error' in res:
                            last_error = res['error']

            if 'error' not in res and res:
                r = res
                used_token = token
                break
        except Exception as e:
            print(f"FB Request Exception: {e}")
            break
            
    if not r or 'error' in r:
        err_msg = (
            r.get('error', {}).get('message')
            if (r and isinstance(r, dict) and 'error' in r)
            else (last_error.get('message') if last_error else "Unknown Error")
        )
        print(f"FB Error for {post_id}: {err_msg}")
        return None

    title = r.get('message', r.get('description', r.get('title', '')))
    
    utc_time = r.get('created_time')
    ist_date = ""
    if utc_time:
        try:
            utc_dt = datetime.strptime(utc_time, "%Y-%m-%dT%H:%M:%S%z")
            ist_date = (utc_dt + timedelta(hours=5, minutes=30)).strftime('%Y-%m-%d')
        except Exception:
            ist_date = str(utc_time)[:10]

    final_views = int(r.get('views', 0)) if is_video_node else 0
    reach = 0

    # 2. Fetch Engagement Safely (Isolated requests so #200 won't break the node)
    comments_count = r.get('comments', {}).get('summary', {}).get('total_count', 0)
    likes_count = r.get('likes', {}).get('summary', {}).get('total_count', 0)
    
    if 'comments' not in r:
        try:
            c_url = f"https://graph.facebook.com/v26.0/{post_id}/comments?summary=true&limit=0&access_token={used_token}"
            c_res = requests.get(c_url).json()
            if 'summary' in c_res:
                comments_count = c_res['summary'].get('total_count', 0)
        except Exception:
            pass

    if 'likes' not in r:
        try:
            l_url = f"https://graph.facebook.com/v26.0/{post_id}/likes?summary=true&limit=0&access_token={used_token}"
            l_res = requests.get(l_url).json()
            if 'summary' in l_res:
                likes_count = l_res['summary'].get('total_count', 0)
        except Exception:
            pass

   # 3. Fetch Insights (Views & Reach)
    try:
        if is_video_node:
            ins_url = (
                f"https://graph.facebook.com/v26.0/{post_id}/video_insights"
                f"?metric=blue_reels_play_count,fb_reels_total_plays,total_video_views,"
                f"post_total_media_view_unique,total_video_views_unique,post_impressions_unique"
                f"&access_token={used_token}"
            )
        else:
            ins_url = (
                f"https://graph.facebook.com/v26.0/{post_id}/insights"
                f"?metric=post_total_media_view_unique,post_video_views,post_media_view,post_impressions,post_impressions_unique"
                f"&access_token={used_token}"
            )
            
        r_ins = requests.get(ins_url).json()
        
        # If Page token fails insights on cross-posted Reels, attempt User token
        alt_token = user_token if used_token == page_token else page_token
        if ('error' in r_ins or not r_ins.get('data')) and alt_token:
            try:
                ins_url_alt = ins_url.replace(used_token, alt_token)
                r_ins_alt = requests.get(ins_url_alt).json()
                if 'data' in r_ins_alt and r_ins_alt['data']:
                    r_ins = r_ins_alt
            except Exception:
                pass
        
        if 'data' in r_ins and r_ins['data']:
            stats = {
                item['name']: int(item['values'][0]['value'])
                for item in r_ins['data']
                if item.get('values') and len(item['values']) > 0
            }
            if is_video_node:
                final_views = (
                    stats.get('blue_reels_play_count')
                    or stats.get('fb_reels_total_plays')
                    or stats.get('total_video_views', final_views)
                )
                reach = (
                    stats.get('post_total_media_view_unique')
                    or stats.get('total_video_views_unique')
                    or stats.get('post_impressions_unique', 0)
                )
            else:
                final_views = (
                    stats.get('post_video_views')
                    or stats.get('post_media_view')
                    or stats.get('post_impressions', 0)
                )
                reach = (
                    stats.get('post_total_media_view_unique')
                    or stats.get('post_impressions_unique', 0)
                )

        # Post-level reach resolution for Reels/Videos if reach is still 0
        if is_video_node and reach == 0:
            target_page_id = page_id or r.get('from', {}).get('id') or globals().get('fb_page_id')
            if target_page_id:
                try:
                    p_url = f"https://graph.facebook.com/v26.0/{target_page_id}_{post_id}/insights?metric=post_total_media_view_unique&access_token={used_token}"
                    p_ins = requests.get(p_url).json()
                    for item in p_ins.get('data', []):
                        if item['name'] == 'post_total_media_view_unique' and item.get('values'):
                            reach = int(item['values'][0]['value'])
                except Exception:
                    pass
            # Fallback to unique initial reel plays (excluding replays) if reach endpoint is withheld
            if reach == 0 and 'stats' in locals():
                reach = stats.get('blue_reels_play_count', 0)
    except Exception as e:
        print(f"FB Insights Exception: {e}")

    # 4. Handle Shares
    shares_count = r.get('shares', {}).get('count', 0)
    if is_video_node and shares_count == 0:
        target_page_id = page_id or r.get('from', {}).get('id') or globals().get('fb_page_id')
        if target_page_id:
            try:
                post_url = f"https://graph.facebook.com/v26.0/{target_page_id}_{post_id}?fields=shares&access_token={used_token}"
                post_res = requests.get(post_url).json()
                shares_count = post_res.get('shares', {}).get('count', 0)
            except Exception:
                shares_count = 0

    permalink = r.get('permalink_url', '')
    if not permalink and post_id:
        permalink = f"https://www.facebook.com/reel/{post_id}" if is_video_node else f"https://www.facebook.com/{post_id}"

    return {
        'date': ist_date,
        'title': title,
        'views': final_views,
        'comments': comments_count,
        'likes': likes_count,
        'shares': shares_count,
        'reach': reach,
        'permalink': permalink
    }

def get_insta_data(media_id):
    if not media_id or len(str(media_id)) < 5: return None
    token = os.environ['INSTAGRAM_TOKEN']
    
    # 1. Basic Info
    url = f"https://graph.facebook.com/v22.0/{media_id}?fields=timestamp,caption,comments_count,like_count,media_product_type,permalink&access_token={token}"
    
    try:
        r = requests.get(url).json()
        if 'error' in r:
            print(f"IG Error: {r['error']['message']}")
            return None

        # --- NEW DATE LOGIC ---
        # Handle ISO format with timezone (e.g. 2026-01-07T19:30:00+0000)
        utc_dt = datetime.strptime(r.get('timestamp'), "%Y-%m-%dT%H:%M:%S%z")
        ist_date = (utc_dt + timedelta(hours=5, minutes=30)).strftime('%Y-%m-%d')
        # ----------------------

        # 2. Insights
        final_views = 0
        reach = 0
        saves = 0
        
        # Determine likely type to choose metric
        is_video = r.get('media_product_type') == 'REELS' or r.get('media_type') == 'VIDEO'
        metrics = "views,reach,saved,shares" if is_video else "impressions,reach,saved,shares"

        shares = 0
        
        try:
            r_ins = requests.get(f"https://graph.facebook.com/v22.0/{media_id}/insights?metric={metrics}&access_token={token}").json()
            if 'data' in r_ins:
                stats = {item['name']: int(item['values'][0]['value']) for item in r_ins['data']}
                if 'views' in stats: final_views = stats['views']
                elif 'impressions' in stats: final_views = stats['impressions']
                reach = stats.get('reach', 0)
                saves = stats.get('saved', 0)
                shares = stats.get('shares', 0)
            elif 'error' in r_ins and is_video:
                 # Fallback for some video types
                 r_retry = requests.get(f"https://graph.facebook.com/v22.0/{media_id}/insights?metric=impressions,reach,saved,shares&access_token={token}").json()
                 if 'data' in r_retry:
                     stats = {item['name']: int(item['values'][0]['value']) for item in r_retry['data']}
                     final_views = stats.get('impressions', 0)
                     reach = stats.get('reach', 0)
                     saves = stats.get('saved', 0)
                     shares = stats.get('shares', 0)
        except: pass

        return {
            'date': ist_date,
            'title': r.get('caption', ''), # Now writes the full caption
            'views': final_views,
            'comments': int(r.get('comments_count', 0)),
            'likes': int(r.get('like_count', 0)),
            'shares': shares,
            'reach': reach,
            'saves': saves,
            'permalink': r.get('permalink', '')
        }
    except Exception as e:
        print(f"IG Exception: {e}")
        return None

# --- NEW HELPERS FOR GLOBAL STATS ---

def update_global_fb_stats(page_id, page_token):
    """Fetches Follower Count for the FB Page"""
    if not page_id or not page_token:
        return
    try:
        acc_res = requests.get(f"https://graph.facebook.com/v22.0/{page_id}?fields=followers_count&access_token={page_token}").json()
        followers = acc_res.get('followers_count', 0)
        print(f"Global Update: Found {followers} FB Followers. Updating {CELL_FB_FOLLOWERS}...")
        sheet.update_acell(CELL_FB_FOLLOWERS, followers)
    except Exception as e:
        print(f"Global FB Update Failed: {e}")

def update_global_insta_stats():
    """Fetches Follower Count for the IG Page"""
    try:
        token = os.environ['INSTAGRAM_TOKEN']
        # Find Page -> IG Business Account -> Followers
        user_res = requests.get(f"https://graph.facebook.com/v22.0/me/accounts?fields=instagram_business_account&access_token={token}").json()
        
        ig_id = None
        if 'data' in user_res:
            for page in user_res['data']:
                if 'instagram_business_account' in page:
                    ig_id = page['instagram_business_account']['id']
                    break
        
        if ig_id:
            # Get Account Info
            acc_res = requests.get(f"https://graph.facebook.com/v22.0/{ig_id}?fields=followers_count&access_token={token}").json()
            followers = acc_res.get('followers_count', 0)
            print(f"Global Update: Found {followers} IG Followers. Updating {CELL_IG_FOLLOWERS}...")
            sheet.update_acell(CELL_IG_FOLLOWERS, followers)
        else:
            print("Global Update: Could not find IG Account ID.")
    except Exception as e:
        print(f"Global IG Update Failed: {e}")

def update_global_yt_stats(channel_id):
    """Fetches Subscriber Count for YT Channel"""
    try:
        api_key = os.environ['YOUTUBE_API_KEY']
        youtube = build('youtube', 'v3', developerKey=api_key)
        res = youtube.channels().list(part="statistics", id=channel_id).execute()
        
        if res['items']:
            subs = int(res['items'][0]['statistics']['subscriberCount'])
            print(f"Global Update: Found {subs} YT Subscribers. Updating {CELL_YT_SUBS}...")
            sheet.update_acell(CELL_YT_SUBS, subs)
    except Exception as e:
        print(f"Global YT Update Failed: {e}")


# --- MAIN ---
if __name__ == "__main__":
    print("Fetching FB Page Token...")
    fb_page_token, fb_page_id = get_fb_page_token_and_id()
    if not fb_page_token:
        print("⚠️ Could not retrieve FB Page Token. FB metrics may fail.")
    
    print("Reading Sheet...")
    all_data = sheet.get_all_values()
    cells_to_update = []
    
    found_yt_channel_id = None # We will grab this from the first video we scan
    
    for i in range(2, len(all_data)):
        row_num = i + 1
        row = all_data[i]
        
        yt_id = row[COL_YT_ID - 1].strip() if len(row) > (COL_YT_ID - 1) else ""
        ig_id = row[COL_IG_ID - 1].strip() if len(row) > (COL_IG_ID - 1) else ""
        fb_id = row[COL_FB_ID - 1].strip() if len(row) > (COL_FB_ID - 1) else ""

        if fb_id and not fb_id.isdigit():
            print(f"⚠️ Skipping invalid FB ID (Not numeric): {fb_id}")
            fb_id = ""
        
        # --- YT ---
        if yt_id:
            yt_data = get_youtube_data(yt_id)
            if yt_data:
                # Capture Channel ID from the first valid video we see
                if not found_yt_channel_id:
                    found_yt_channel_id = yt_data['channel_id']
                
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
                cells_to_update.append(gspread.Cell(row_num, COL_IG_SHARES, ig_data.get('shares', 0)))
                cells_to_update.append(gspread.Cell(row_num, COL_IG_SAVES, ig_data['saves']))
                cells_to_update.append(gspread.Cell(row_num, COL_IG_REACH, ig_data['reach']))
                # --- NEW: Write real hyperlink to the IG_ID column ---
                if ig_data.get('permalink'):
                    ig_formula = f'=HYPERLINK("{ig_data["permalink"]}", "{ig_id}")'
                    cells_to_update.append(gspread.Cell(row_num, COL_IG_ID, ig_formula))
                
                if not yt_id:
                    cells_to_update.append(gspread.Cell(row_num, COL_DATE, ig_data['date']))
                    cells_to_update.append(gspread.Cell(row_num, COL_TITLE, ig_data['title']))

        # --- FB ---
        if fb_id:
            fb_data = get_facebook_data(fb_id, fb_page_token)
            if fb_data:
                cells_to_update.append(gspread.Cell(row_num, COL_FB_VIEWS, fb_data['views']))
                cells_to_update.append(gspread.Cell(row_num, COL_FB_LIKES, fb_data['likes']))
                cells_to_update.append(gspread.Cell(row_num, COL_FB_COMMENTS, fb_data['comments']))
                cells_to_update.append(gspread.Cell(row_num, COL_FB_SHARES, fb_data['shares']))
                cells_to_update.append(gspread.Cell(row_num, COL_FB_REACH, fb_data['reach']))
                
                if fb_data.get('permalink'):
                    fb_formula = f'=HYPERLINK("{fb_data["permalink"]}", "{fb_id}")'
                    cells_to_update.append(gspread.Cell(row_num, COL_FB_ID, fb_formula))
                
                if not yt_id and not ig_id:
                    cells_to_update.append(gspread.Cell(row_num, COL_DATE, fb_data['date']))
                    cells_to_update.append(gspread.Cell(row_num, COL_TITLE, fb_data['title']))
        
        time.sleep(0.2)

    if cells_to_update:
        print(f"Updating {len(cells_to_update)} rows...")
        sheet.update_cells(cells_to_update, value_input_option='USER_ENTERED')
    
    # --- RUN GLOBAL STATS ---
    print("\n--- Updating Global Counters ---")
    update_global_insta_stats()
    
    if fb_page_id and fb_page_token:
        update_global_fb_stats(fb_page_id, fb_page_token)
    
    if found_yt_channel_id:
        update_global_yt_stats(found_yt_channel_id)
    else:
        print("Skipping YT Subs update (No YT Video found in sheet to extract Channel ID).")

    print("Success!")
