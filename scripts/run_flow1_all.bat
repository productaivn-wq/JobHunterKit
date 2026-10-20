@echo off
:: Batch wrapper for Flow 1 (Scrape All Sources)
:: Runs flow_scrape.py across all 14 job board sources with logging enabled

"C:\Users\user\AppData\Local\Programs\Python\Python312\python.exe" -u "%~dp0flow_scrape.py" --keyword "Product Manager" --location "Singapore" --source "all" --log
