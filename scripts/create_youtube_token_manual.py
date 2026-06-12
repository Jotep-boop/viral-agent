from urllib.parse import urlparse, parse_qs
from google_auth_oauthlib.flow import InstalledAppFlow
import pickle
import os
from pathlib import Path

# Required for manual localhost OAuth callback handling in a non-listening environment.
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube.readonly',
    'https://www.googleapis.com/auth/youtube.force-ssl',
]
BASE_DIR = Path(__file__).resolve().parent.parent
TOKEN_PATH = BASE_DIR / 'youtube_token.json'
REDIRECT_URI = 'http://localhost'

flow = InstalledAppFlow.from_client_secrets_file(str(BASE_DIR / 'client_secrets.json'), SCOPES)
flow.redirect_uri = REDIRECT_URI

auth_url, _ = flow.authorization_url(
    access_type='offline',
    prompt='consent',
    include_granted_scopes='true',
)

print('OPEN_THIS_URL', flush=True)
print(auth_url, flush=True)
print('PASTE_FINAL_REDIRECT_URL', flush=True)
redirected_url = input().strip()

parsed = urlparse(redirected_url)
qs = parse_qs(parsed.query)
if 'error' in qs:
    raise SystemExit(f"OAuth error: {qs['error'][0]}")
if 'code' not in qs:
    raise SystemExit('No code found in pasted URL')

flow.fetch_token(authorization_response=redirected_url)
with open(TOKEN_PATH, 'wb') as f:
    pickle.dump(flow.credentials, f)
print(f'TOKEN_SAVED {os.path.abspath(TOKEN_PATH)}', flush=True)
