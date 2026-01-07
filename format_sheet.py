import os
import json
import gspread
from google.oauth2.service_account import Credentials

# --- SETUP ---
json_creds = json.loads(os.environ['GOOGLE_SHEETS_JSON'])
SCOPE = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_info(json_creds, scopes=SCOPE)
client = gspread.authorize(creds)
sheet = client.open_by_key(os.environ['SHEET_KEY']).sheet1 

def apply_date_format():
    print("Applying custom date format to Column A...")
    
    # The format pattern you wanted: "Tue, 07-Jan-2026"
    # In Google Sheets syntax, this is: "ddd, dd-mmm-yyyy"
    
    requests = [{
        "repeatCell": {
            "range": {
                "sheetId": sheet.id,
                "startRowIndex": 2, # Skip Header (Row 1 & 2)
                "startColumnIndex": 0, # Column A
                "endColumnIndex": 1    # Column A only
            },
            "cell": {
                "userEnteredFormat": {
                    "numberFormat": {
                        "type": "DATE",
                        "pattern": "ddd, dd-mmm-yyyy" 
                    }
                }
            },
            "fields": "userEnteredFormat.numberFormat"
        }
    }]

    # Send the update
    sheet.spreadsheet.batch_update({"requests": requests})
    print("✅ Date format applied successfully!")

if __name__ == "__main__":
    apply_date_format()
