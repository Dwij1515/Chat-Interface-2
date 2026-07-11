import os
import re
import json
import base64
import requests
import logging
import imaplib
import email
from email.header import decode_header
from datetime import datetime

logger = logging.getLogger(__name__)

# Mock Data Definitions
MOCK_EMAILS = [
    {
        "id": "msg_001",
        "from": "ceo@company.com",
        "subject": "Urgent: Top Important Project Roadmap",
        "date": "2026/07/11",
        "body": "Hi Team, please find the top important Q3 roadmap attached. We need to align on these goals immediately.",
        "attachments": [{"filename": "Q3_Roadmap.pdf", "content": "JVBERi0xLjQKJVRlc3QgUERGIENvbnRlbnQK"}] # base64 mock
    },
    {
        "id": "msg_002",
        "from": "billing@cloudservices.com",
        "subject": "Monthly Invoice #9982",
        "date": "2026/07/10",
        "body": "Dear Customer, your invoice for the month of June is attached. Amount due: $345.00.",
        "attachments": [{"filename": "invoice_9982.pdf", "content": "JVBERi0xLjQKJVRlc3QgSW52b2ljZSBDb250ZW50Cg=="}]
    },
    {
        "id": "msg_003",
        "from": "newsletter@techcrunch.com",
        "subject": "Weekly AI Advancements and Robotics",
        "date": "2026/07/08",
        "body": "Welcome to this week's digest. Today, we cover the launch of GPT-5, the new Groq hardware, and agentic workflows.",
        "attachments": []
    },
    {
        "id": "msg_004",
        "from": "hr@company.com",
        "subject": "New Policy Guidelines for Remote Work",
        "date": "2026/06/15",
        "body": "All employees are requested to read the updated remote work guidelines attached below.",
        "attachments": [{"filename": "Remote_Work_Guidelines.docx", "content": "TW9jayBEb2N1bWVudCBDb250ZW50"}]
    },
    {
        "id": "msg_005",
        "from": "operations@company.com",
        "subject": "Inventory Audit Results",
        "date": "2026/05/20",
        "body": "Here is the final report for the inventory audit conducted last month.",
        "attachments": [{"filename": "inventory_audit.xlsx", "content": "TW9jayBFeGNlbCBDb250ZW50"}]
    }
]

class ComposiaSDK:
    def __init__(self, weather_api_key=None, gmail_credentials_path=None, google_credentials_path=None):
        self.weather_api_key = weather_api_key or os.getenv("OPENWEATHER_API_KEY")
        self.gmail_credentials_path = gmail_credentials_path or os.getenv("GOOGLE_CLIENT_SECRET_FILE")
        self.google_credentials_path = google_credentials_path or os.getenv("GOOGLE_CLIENT_SECRET_FILE")
        self.gmail_user = os.getenv("GMAIL_USER")
        self.gmail_app_password = os.getenv("GMAIL_APP_PASSWORD")
        
        # Determine paths
        self.attachments_dir = "attachments"
        os.makedirs(self.attachments_dir, exist_ok=True)
        
        # Local mock database for spreadsheet data
        self.mock_sheets_file = "mock_sheets_database.json"
        if not os.path.exists(self.mock_sheets_file):
            with open(self.mock_sheets_file, "w") as f:
                json.dump({}, f)
                
        # API Client Flags
        self.use_real_weather = bool(self.weather_api_key and "your" not in self.weather_api_key and len(self.weather_api_key) > 10)
        self.use_real_google = False
        self.use_imap = bool(self.gmail_user and self.gmail_app_password)
        
        # Try to initialize real Google Clients if credentials path exists
        if self.google_credentials_path and os.path.exists(self.google_credentials_path):
            try:
                from google.oauth2.credentials import Credentials
                from google_auth_oauthlib.flow import InstalledAppFlow
                from google.auth.transport.requests import Request
                from googleapiclient.discovery import build
                
                # Check for token.json
                self.scopes = [
                    'https://www.googleapis.com/auth/gmail.readonly',
                    'https://www.googleapis.com/auth/spreadsheets'
                ]
                self.creds = None
                if os.path.exists('token.json'):
                    self.creds = Credentials.from_authorized_user_file('token.json', self.scopes)
                
                if not self.creds or not self.creds.valid:
                    if self.creds and self.creds.expired and self.creds.refresh_token:
                        self.creds.refresh(Request())
                    else:
                        flow = InstalledAppFlow.from_client_secrets_file(
                            self.google_credentials_path, self.scopes)
                        self.creds = flow.run_local_server(port=0)
                    # Save the credentials for the next run
                    with open('token.json', 'w') as token:
                        token.write(self.creds.to_json())
                
                if self.creds:
                    self.gmail_service = build('gmail', 'v1', credentials=self.creds)
                    self.sheets_service = build('sheets', 'v4', credentials=self.creds)
                    self.use_real_google = True
                    logger.info("Successfully initialized real Google API services.")
            except Exception as e:
                logger.error(f"Failed to initialize real Google Services, falling back to mock: {e}")
                self.use_real_google = False
        else:
            logger.info("Credentials file not found. Operating Google features in Mock mode.")

    def _connect_imap(self):
        """Connect to IMAP server using environment credentials"""
        if not self.gmail_user or not self.gmail_app_password:
            raise ValueError("Gmail IMAP user or password not configured in .env.")
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(self.gmail_user, self.gmail_app_password)
        return mail

    def _parse_imap_message(self, mail, e_id):
        status, msg_data = mail.fetch(e_id, "(RFC822)")
        for response_part in msg_data:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])
                
                # Decode subject
                subject = "No Subject"
                if msg["Subject"]:
                    try:
                        decoded = decode_header(msg["Subject"])
                        parts = []
                        for sub, enc in decoded:
                            if isinstance(sub, bytes):
                                parts.append(sub.decode(enc or "utf-8", errors="ignore"))
                            else:
                                parts.append(str(sub))
                        subject = "".join(parts)
                    except Exception:
                        subject = str(msg["Subject"])
                
                # Decode from
                sender = "Unknown Sender"
                if msg["From"]:
                    try:
                        decoded = decode_header(msg["From"])
                        parts = []
                        for s, enc in decoded:
                            if isinstance(s, bytes):
                                parts.append(s.decode(enc or "utf-8", errors="ignore"))
                            else:
                                parts.append(str(s))
                        sender = "".join(parts)
                    except Exception:
                        sender = str(msg["From"])
                
                # Date
                date = msg["Date"] or "Unknown Date"
                
                return {
                    "id": e_id.decode(),
                    "from": sender,
                    "subject": subject,
                    "date": date
                }
        return None

    # WEATHER API
    def get_weather(self, location):
        """Fetch current weather for a city"""
        if not location:
            return {"error": "Location must be specified."}
            
        if self.use_real_weather:
            url = f"http://api.openweathermap.org/data/2.5/weather?q={location}&appid={self.weather_api_key}&units=metric"
            try:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "location": data["name"],
                        "temperature": data["main"]["temp"],
                        "description": data["weather"][0]["description"].capitalize(),
                        "humidity": data["main"]["humidity"],
                        "wind_speed": data["wind"]["speed"]
                    }
                elif response.status_code == 404:
                    return {"error": f"City '{location}' not found."}
                else:
                    return {"error": f"Weather API error (status code: {response.status_code})"}
            except Exception as e:
                logger.error(f"Error calling Weather API: {e}")
                # Fallthrough to mock
        
        # Mock weather fallback
        logger.info(f"Using Mock Weather for '{location}'")
        h = sum(ord(c) for c in location)
        temp = 14 + (h % 18)
        humidity = 45 + (h % 40)
        wind = 2.0 + (h % 8) / 2.0
        conditions = ["Sunny", "Partly Cloudy", "Overcast", "Light Rain", "Scattered Showers", "Breezy"]
        desc = conditions[h % len(conditions)]
        return {
            "location": location.strip().title(),
            "temperature": temp,
            "description": desc,
            "humidity": humidity,
            "wind_speed": wind
        }

    # GMAIL / EMAIL API
    def get_latest_emails(self):
        """Fetch latest emails"""
        if self.use_imap:
            try:
                mail = self._connect_imap()
                mail.select("inbox")
                status, messages = mail.search(None, "ALL")
                email_ids = messages[0].split()
                # Get latest 10
                latest_ids = email_ids[-10:]
                latest_ids.reverse()
                
                emails = []
                for e_id in latest_ids:
                    parsed = self._parse_imap_message(mail, e_id)
                    if parsed:
                        emails.append(parsed)
                mail.logout()
                return emails
            except Exception as e:
                logger.error(f"IMAP get_latest_emails failed: {e}")
                return {"error": f"Failed to retrieve emails: {str(e)}"}

        if self.use_real_google:
            try:
                results = self.gmail_service.users().messages().list(userId='me', maxResults=10).execute()
                messages = results.get('messages', [])
                emails = []
                for msg in messages:
                    msg_detail = self.gmail_service.users().messages().get(userId='me', id=msg['id']).execute()
                    headers = msg_detail.get('payload', {}).get('headers', [])
                    
                    subject = "No Subject"
                    sender = "Unknown Sender"
                    date = "Unknown Date"
                    
                    for h in headers:
                        if h['name'].lower() == 'subject':
                            subject = h['value']
                        elif h['name'].lower() == 'from':
                            sender = h['value']
                        elif h['name'].lower() == 'date':
                            date = h['value']
                            
                    emails.append({
                        "id": msg['id'],
                        "from": sender,
                        "subject": subject,
                        "date": date
                    })
                return emails
            except Exception as e:
                logger.error(f"Gmail get_latest_emails failed: {e}")
                return {"error": f"Failed to retrieve emails: {str(e)}"}
                
        # Return Mock Emails
        return [{"id": m["id"], "from": m["from"], "subject": m["subject"], "date": m["date"]} for m in MOCK_EMAILS]

    def get_emails_between_dates(self, start_date, end_date):
        """Fetch emails between start_date and end_date (YYYY/MM/DD)"""
        # Parse inputs to date objects
        try:
            start_dt = datetime.strptime(start_date, "%Y/%m/%d")
            end_dt = datetime.strptime(end_date, "%Y/%m/%d")
        except Exception as e:
            return {"error": "Invalid date format. Use YYYY/MM/DD."}
            
        if self.use_imap:
            from datetime import timedelta
            imap_start = start_dt.strftime("%d-%b-%Y")
            end_plus_one = end_dt + timedelta(days=1)
            imap_end = end_plus_one.strftime("%d-%b-%Y")
            try:
                mail = self._connect_imap()
                mail.select("inbox")
                search_query = f'(SINCE "{imap_start}" BEFORE "{imap_end}")'
                status, messages = mail.search(None, search_query)
                email_ids = messages[0].split()
                email_ids = email_ids[-20:]
                email_ids.reverse()
                
                emails = []
                for e_id in email_ids:
                    parsed = self._parse_imap_message(mail, e_id)
                    if parsed:
                        emails.append(parsed)
                mail.logout()
                return emails
            except Exception as e:
                logger.error(f"IMAP get_emails_between_dates failed: {e}")
                return {"error": f"Failed to retrieve emails: {str(e)}"}

        if self.use_real_google:
            try:
                # Query in Gmail format: after:YYYY/MM/DD before:YYYY/MM/DD
                q = f"after:{start_date} before:{end_date}"
                results = self.gmail_service.users().messages().list(userId='me', q=q).execute()
                messages = results.get('messages', [])
                emails = []
                for msg in messages:
                    msg_detail = self.gmail_service.users().messages().get(userId='me', id=msg['id']).execute()
                    headers = msg_detail.get('payload', {}).get('headers', [])
                    subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), "No Subject")
                    sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), "Unknown Sender")
                    date = next((h['value'] for h in headers if h['name'].lower() == 'date'), "Unknown Date")
                    
                    emails.append({
                        "id": msg['id'],
                        "from": sender,
                        "subject": subject,
                        "date": date
                    })
                return emails
            except Exception as e:
                logger.error(f"Gmail query failed: {e}")
                return {"error": str(e)}

        # Mock query
        filtered = []
        for m in MOCK_EMAILS:
            try:
                m_dt = datetime.strptime(m["date"], "%Y/%m/%d")
                if start_dt <= m_dt <= end_dt:
                    filtered.append({"id": m["id"], "from": m["from"], "subject": m["subject"], "date": m["date"]})
            except Exception:
                continue
        return filtered

    def search_emails_by_subject(self, subject_query):
        """Search emails containing query in subject"""
        if not subject_query:
            return {"error": "Query cannot be empty."}
            
        if self.use_imap:
            try:
                mail = self._connect_imap()
                mail.select("inbox")
                status, messages = mail.search(None, f'SUBJECT "{subject_query}"')
                email_ids = messages[0].split()
                email_ids = email_ids[-20:]
                email_ids.reverse()
                
                emails = []
                for e_id in email_ids:
                    parsed = self._parse_imap_message(mail, e_id)
                    if parsed:
                        emails.append(parsed)
                mail.logout()
                return emails
            except Exception as e:
                logger.error(f"IMAP search_emails_by_subject failed: {e}")
                return {"error": f"Failed to retrieve emails: {str(e)}"}

        if self.use_real_google:
            try:
                q = f"subject:({subject_query})"
                results = self.gmail_service.users().messages().list(userId='me', q=q).execute()
                messages = results.get('messages', [])
                emails = []
                for msg in messages:
                    msg_detail = self.gmail_service.users().messages().get(userId='me', id=msg['id']).execute()
                    headers = msg_detail.get('payload', {}).get('headers', [])
                    subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), "No Subject")
                    sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), "Unknown Sender")
                    date = next((h['value'] for h in headers if h['name'].lower() == 'date'), "Unknown Date")
                    emails.append({
                        "id": msg['id'],
                        "from": sender,
                        "subject": subject,
                        "date": date
                    })
                return emails
            except Exception as e:
                return {"error": str(e)}

        # Mock search
        q_lower = subject_query.lower()
        filtered = []
        for m in MOCK_EMAILS:
            if q_lower in m["subject"].lower():
                filtered.append({"id": m["id"], "from": m["from"], "subject": m["subject"], "date": m["date"]})
        return filtered

    def save_attachments(self, email_id):
        """Save attachments for a specific email_id and return their local paths"""
        if self.use_imap:
            try:
                mail = self._connect_imap()
                mail.select("inbox")
                status, msg_data = mail.fetch(email_id.encode(), "(RFC822)")
                saved_files = []
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        for part in msg.walk():
                            if part.get_content_maintype() == 'multipart':
                                continue
                            if part.get('Content-Disposition') is None:
                                continue
                            filename = part.get_filename()
                            if filename:
                                try:
                                    decoded = decode_header(filename)
                                    parts = []
                                    for f, enc in decoded:
                                        if isinstance(f, bytes):
                                            parts.append(f.decode(enc or "utf-8", errors="ignore"))
                                        else:
                                            parts.append(str(f))
                                    filename = "".join(parts)
                                except Exception:
                                    pass
                                
                                filename = os.path.basename(filename)
                                filepath = os.path.join(self.attachments_dir, filename)
                                payload = part.get_payload(decode=True)
                                if payload:
                                    with open(filepath, "wb") as f:
                                        f.write(payload)
                                    saved_files.append({"filepath": filepath})
                mail.logout()
                return saved_files
            except Exception as e:
                logger.error(f"IMAP save_attachments failed: {e}")
                return {"error": f"Failed to download attachments: {str(e)}"}

        if self.use_real_google:
            try:
                msg = self.gmail_service.users().messages().get(userId='me', id=email_id).execute()
                parts = msg.get('payload', {}).get('parts', [])
                saved_files = []
                for part in parts:
                    if part.get('filename') and part.get('body', {}).get('attachmentId'):
                        att_id = part['body']['attachmentId']
                        filename = part['filename']
                        att = self.gmail_service.users().messages().attachments().get(
                            userId='me', messageId=email_id, id=att_id
                        ).execute()
                        data = base64.urlsafe_b64decode(att['data'].encode('UTF-8'))
                        
                        filepath = os.path.join(self.attachments_dir, filename)
                        with open(filepath, "wb") as f:
                            f.write(data)
                            
                        saved_files.append({"filepath": filepath})
                return saved_files
            except Exception as e:
                return {"error": str(e)}

        # Mock download
        for m in MOCK_EMAILS:
            if m["id"] == email_id:
                saved = []
                for att in m["attachments"]:
                    filepath = os.path.join(self.attachments_dir, att["filename"])
                    try:
                        file_data = base64.b64decode(att["content"])
                        with open(filepath, "wb") as f:
                            f.write(file_data)
                        saved.append({"filepath": filepath})
                    except Exception as e:
                        logger.error(f"Failed to write mock attachment: {e}")
                return saved
        return {"error": "Email not found."}

    # SPREADSHEET API
    def insert_spreadsheet_data(self, spreadsheet_id, range_name, values):
        """Insert data rows into a spreadsheet"""
        if self.use_real_google:
            try:
                body = {'values': values}
                result = self.sheets_service.spreadsheets().values().update(
                    spreadsheetId=spreadsheet_id,
                    range=range_name,
                    valueInputOption='USER_ENTERED',
                    body=body
                ).execute()
                return {"updatedCells": result.get('updatedCells', 0)}
            except Exception as e:
                return {"error": str(e)}

        # Mock local sheet persistence
        try:
            with open(self.mock_sheets_file, "r") as f:
                db = json.load(f)
                
            sheet_key = f"{spreadsheet_id}::{range_name}"
            db[sheet_key] = values
            
            with open(self.mock_sheets_file, "w") as f:
                json.dump(db, f)
                
            return {"updatedCells": len(values) * len(values[0]) if values else 0}
        except Exception as e:
            return {"error": str(e)}

    def fetch_spreadsheet_data(self, spreadsheet_id, range_name):
        """Fetch rows from a spreadsheet range"""
        if self.use_real_google:
            try:
                result = self.sheets_service.spreadsheets().values().get(
                    spreadsheetId=spreadsheet_id, range=range_name
                ).execute()
                return result.get('values', [])
            except Exception as e:
                return {"error": str(e)}

        # Mock sheet retrieval
        try:
            with open(self.mock_sheets_file, "r") as f:
                db = json.load(f)
            sheet_key = f"{spreadsheet_id}::{range_name}"
            return db.get(sheet_key, [["Header1", "Header2"], ["Mock Data A", "Mock Data B"]])
        except Exception as e:
            return {"error": str(e)}
