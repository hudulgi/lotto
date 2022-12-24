import os

try:
    from selenium import webdriver
except:
    os.system("pip install --upgrade selenium")

try:
    from webdriver_manager.chrome import ChromeDriverManager
except:
    os.system("pip install webdriver-manager")


