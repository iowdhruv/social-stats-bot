import os
import json
import gspread
from google.oauth2.service_account import Credentials

# --- CONFIG ---
# Target Column A (Index 0)
COL_INDEX = 0 
CHAR_LIMIT_FOR_DOUBLE = 40 # Approx chars that fit in 1 line. Adjust if needed.

# --- SETUP ---
json_creds = json.loads(os.environ['GOOGLE_SHEETS_JSON'])
SCOPE = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_info(json_creds, scopes=SCOPE)
client = gspread.authorize(creds)
sheet = client.open_by_key(os.environ['SHEET_KEY']).sheet1 

def fix_formatting():
    print("Surgically fixing Date formats in Column A...")
    
    # 1. Get Values to determine heights
   
    # OLD CODE: sheet.col_values(COL_INDEX + 1) # 1-based index for col_values
    # We need Column B (Index 1) for text length
    col_a_values = sheet.col_values(1) # Date
    col_b_values = sheet.col_values(2) # Title/Caption
    col_values = col_a_values 

    # ----- NEW: SANITIZE TITLES (Column B) -----
    # Collapse double/triple newlines into a single newline
    title_updates = []
    
    for index, title in enumerate(col_b_values):
        # Skip headers (rows 0 and 1)
        if index < 2: 
            continue
            
        # Check if there are double newlines
        if title and "\n\n" in title:
            clean_title = title
            # Keep replacing \n\n with \n until none are left
            while "\n\n" in clean_title:
                clean_title = clean_title.replace("\n\n", "\n")
            
            # Update local list so row height calculation is accurate
            col_b_values[index] = clean_title 
            
            # Prepare batch update
            title_updates.append({
                'range': f'B{index + 1}', 
                'values': [[clean_title]]
            })

    if title_updates:
        sheet.batch_update(title_updates)
        print(f"✅ Collapsed empty lines in {len(title_updates)} titles.")
    
    # ----------------------------------------

    
    # ----- NEW: HYPERLINK IDs (Columns M & N) -----
    
    col_m_values = sheet.col_values(13) # YT_ID
    col_n_values = sheet.col_values(14) # IG_ID
    id_updates = []

    for i in range(2, len(col_values)):
        yt_id = col_m_values[i].strip() if i < len(col_m_values) else ""
        ig_id = col_n_values[i].strip() if i < len(col_n_values) else ""
        
        if yt_id and not str(yt_id).startswith("=HYPERLINK"):
            yt_url = f"https://www.youtube.com/watch?v={yt_id}"
            id_updates.append({'range': f'M{i + 1}', 'values': [[f'=HYPERLINK("{yt_url}", "{yt_id}")']]})
            
    if id_updates:
        sheet.batch_update(id_updates, value_input_option='USER_ENTERED')
        print(f"✅ Converted {len(id_updates)} IDs into clickable hyperlinks.")
        
    # ----------------------------------------------
    
    # 2. Prepare updates just for Column A
    # We will re-write Column A using 'USER_ENTERED' mode.
    # This forces Sheets to parse '2026-01-07' into a Date Object.
    # Because we ONLY write to Col A, the IDs in Col M/N are safe!
    
    updates = []
    # Skip header (Row 1 & 2), start from Row 3 (Index 2)
    for i in range(2, len(col_values)):
        val = col_values[i]
        if val: # Only if not empty
            updates.append({
                'range': f'A{i+1}', 
                'values': [[val]]
            })

    if updates:
        # Batch update allows different input options per range, 
        # but gspread's batch_update doesn't support valueInputOption per range easily.
        # So we use a loop or a specific range update.
        # Efficient way: Update the whole column A at once.
        
        # Get the range for the data part of Column A (e.g., A3:A100)
        data_range = f"A3:A{len(col_values)}"
        data_values = [[v] for v in col_values[2:]] # Slice off headers
        
        # WRITE ONLY TO COLUMN A with USER_ENTERED
        sheet.update(range_name=data_range, values=data_values, value_input_option='USER_ENTERED')
        
        print("✅ Column A converted to Date Objects.")

    # 3.Visual Formatting Rules
    # Prepare updates
    requests = []
    
    # Rule A: Formate date column (col A) (format eg: Thu, 7-Aug-2025)
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet.id,
                "startRowIndex": 2, 
                "startColumnIndex": 0, 
                "endColumnIndex": 1
            },
            "cell": {
                "userEnteredFormat": {
                    "numberFormat": {
                        "type": "DATE",
                        "pattern": "ddd, d-mmm-yyyy" 
                    }
                }
            },
            "fields": "userEnteredFormat.numberFormat"
        }
    }) 

    print("Applying Smart Adaptive text formatting...")
    
    # Rule B: FORMAT TEXT (Col B) - Wrap + Top Align
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet.id,
                "startRowIndex": 2, 
                "startColumnIndex": 1, # Col B
                "endColumnIndex": 2
            },
            "cell": {
                "userEnteredFormat": {
                    "wrapStrategy": "WRAP",       # Allow wrapping
                    "verticalAlignment": "TOP",   # Ensure we see the START of the caption
                    "horizontalAlignment": "CENTER"
                }
            },
            "fields": "userEnteredFormat(wrapStrategy,verticalAlignment,horizontalAlignment)"
        }
    })
    
    # Rule C: SMART ROW HEIGHTS (The Vertical Cutoff)
    # We calculate height row by row based on text length
    for i in range(2, len(col_a_values)):
        # Get caption text (safely handle missing rows in Col B)
        text = col_b_values[i] if i < len(col_b_values) else ""
        
        # LOGIC: Short -> 21px, Long -> 42px
        height = 40 if len(text) > CHAR_LIMIT_FOR_DOUBLE else 21

        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet.id,
                    "dimension": "ROWS",
                    "startIndex": i,
                    "endIndex": i + 1
                },
                "properties": {
                    "pixelSize": height
                },
                "fields": "pixelSize"
            }
        })

    # Send all requests
    if requests:
        sheet.spreadsheet.batch_update({"requests": requests})
        print(f"✅ Smart Formatting applied to {len(col_a_values)-2} rows.")

if __name__ == "__main__":
    fix_formatting()
