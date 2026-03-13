"""
연관 검색어 셀렉터 디버깅용 스크립트
실행: python debug_scraper.py
→ page_source.html 파일로 저장 후 어떤 요소에 연관 검색어가 있는지 확인
"""
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time

query = "장기요양등급신청"

options = Options()
options.add_argument("--headless=new")
options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option("useAutomationExtension", False)
options.add_argument("--log-level=3")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")

service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service, options=options)
driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument",
    {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"})

driver.get(f"https://www.google.com/search?q={query.replace(' ','+')}&hl=ko&gl=KR")
WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "search")))
time.sleep(1.5)

# 스크롤 후 대기
driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
time.sleep(2)

# 페이지 소스 저장
with open("page_source.html", "w", encoding="utf-8") as f:
    f.write(driver.page_source)
print("page_source.html 저장 완료")

# 연관 검색어가 있을 법한 셀렉터 후보 전부 출력
candidates = driver.execute_script("""
    const results = {};

    const selectors = [
        '#botstuff',
        '[data-q]',
        '.Q71vJc', '.s75CSd', '.AB4Wff', '.k8XOCe',
        '.EIaa9b', '.dg6jd', '.YsGUOb', '.oatEtb',
        '#bres', '#brs',
    ];

    for (const sel of selectors) {
        const els = document.querySelectorAll(sel);
        if (els.length > 0) {
            results[sel] = Array.from(els).slice(0, 5).map(el => ({
                tag: el.tagName,
                text: el.textContent.trim().slice(0, 80),
                dataQ: el.getAttribute('data-q'),
                classes: el.className
            }));
        }
    }
    return results;
""")

print("\n=== 셀렉터별 발견된 요소 ===")
for sel, items in candidates.items():
    print(f"\n[{sel}] ({len(items)}개)")
    for item in items:
        print(f"  tag={item['tag']} | data-q={item['dataQ']} | text={item['text'][:60]}")

driver.quit()
