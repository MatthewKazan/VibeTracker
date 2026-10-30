import errno,json,socket,sqlite3,urllib.error,zipfile

def explain(error):
 text=str(error);low=text.lower()
 if isinstance(error,urllib.error.HTTPError):
  if error.code in (401,403):return 'The website denied access. Paste the job description into Add application instead.'
  if error.code==429:return 'The service is rate-limiting requests. Wait a minute and try again.'
  return 'The external service returned an error. Try again later, or paste the job description manually.'
 if isinstance(error,(TimeoutError,socket.timeout)):return 'The request timed out. Check your connection; for local AI, try a smaller model and close other memory-heavy apps.'
 if isinstance(error,urllib.error.URLError):return 'Could not reach the service. Check your internet connection, or open Local AI and start Ollama.'
 if isinstance(error,PermissionError):return 'The app cannot write to its data folder. Open File → Open data folder and check that your account can write there, then restart.'
 if isinstance(error,OSError) and error.errno==errno.ENOSPC:return 'The disk is full. Free disk space and retry. Keep the form open until saving succeeds.'
 if isinstance(error,sqlite3.DatabaseError):
  if 'locked' in low:return 'The database is busy. Close other JobTracker windows and retry in a few seconds.'
  if 'readonly' in low:return 'The data folder is read-only. Check its write permissions, then restart JobTracker.'
  return 'The database could not be read or saved. Keep a copy of the data folder and recover from a backup; do not delete the database.'
 if isinstance(error,zipfile.BadZipFile):return 'This is not a readable Excel workbook. Open it in Excel and save a new .xlsx or CSV copy, then import that copy.'
 if isinstance(error,UnicodeDecodeError):return 'The CSV is not UTF-8. In Excel, save it as CSV UTF-8 and try again.'
 if isinstance(error,json.JSONDecodeError):return 'The response or backup is not valid JSON. For a backup, select a JobTracker JSON export; for AI, retry with another model.'
 if isinstance(error,ValueError):return text
 return 'The operation could not be completed. Retry once; if it continues, restart JobTracker and keep a copy of your data folder. Details: '+text[:250]
