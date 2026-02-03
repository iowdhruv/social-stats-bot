import os
import json
import gspread
from google.oauth2.service_account import Credentials

# --- CONFIG ---
# Target Column A (Index 0)
COL_INDEX = 0 

# --- SETUP ---
json_creds = json.loads(os.environ['GOOGLE_SHEETS_JSON'])
SCOPE = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_info(json_creds, scopes=SCOPE)
client = gspread.authorize(creds)
sheet = client.open_by_key(os.environ['SHEET_KEY']).sheet1 

def fix_dates():
    print("Surgically fixing Date formats in Column A...")
    
    # 1. Get all values in Column A
    col_values = sheet.col_values(COL_INDEX + 1) # 1-based index for col_values
    
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
        sheet.update(values=data_values, range_name=data_range, value_input_option='USER_ENTERED')
        
        print("✅ Column A converted to Date Objects.")

    # 3. Apply the Visual Format "Tue, 7-Jan-2026"
    requests = [{
        # Rule A: Formate date column (col A)
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
    }, 
        # Rule B: CLIP the content title (col B) so rows dont get huge
    {
        "repeatCell": {
            "range": {
                "sheetId": sheet.id,
                "startRowIndex": 2,    # Start from Row 3 (skip headers)
                "startColumnIndex": 1, # Column B (Index 1)
                "endColumnIndex": 2    # End at Column C (Index 2)
            },
            "cell": {
                "userEnteredFormat": {
                    "wrapStrategy": "CLIP" # <--- This fixes the height issue
                }
            },
            "fields": "userEnteredFormat.wrapStrategy"
        }
    }]
    
    sheet.spreadsheet.batch_update({"requests": requests})
    print("✅ Visual Format Applied.")

if __name__ == "__main__":
    fix_dates()
