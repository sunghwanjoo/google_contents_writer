# ============================================================
# 구글 검색 결과 1페이지 제목 스크래핑 프로그램
# 속도 최적화: Chrome 인스턴스 재사용 (매 검색마다 재시작 X)
# ============================================================

import time
import threading

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


# ── 전역 드라이버 (한 번만 생성 후 재사용) ──────────────────────
_driver = None
_driver_lock = threading.Lock()


def _build_options() -> Options:
    """Chrome 옵션 생성 (속도 최적화)"""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    # 속도 최적화
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-plugins")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-default-apps")
    options.add_argument("--disable-sync")
    options.add_argument("--no-first-run")
    options.add_argument("--mute-audio")
    options.add_argument("--disable-translate")
    options.add_argument("--disable-notifications")
    options.add_argument("--log-level=3")
    options.add_argument("--blink-settings=imagesEnabled=false")  # 이미지 비활성화

    # 페이지 로딩 전략: HTML+JS만 기다리고 나머지 리소스는 기다리지 않음
    options.page_load_strategy = "eager"

    # 이미지·알림 비활성화
    options.add_experimental_option("prefs", {
        "profile.managed_default_content_settings.images": 2,
        "profile.default_content_setting_values.notifications": 2,
    })

    return options


def _create_driver() -> webdriver.Chrome:
    """Chrome 드라이버 생성"""
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=_build_options())
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"}
    )
    return driver


def _get_driver() -> webdriver.Chrome:
    """
    전역 드라이버 반환 (없으면 생성, 죽었으면 재생성)
    → Chrome 재시작 비용(3~5초) 제거
    """
    global _driver
    with _driver_lock:
        if _driver is not None:
            try:
                # 드라이버 살아있는지 확인
                _ = _driver.current_url
            except Exception:
                # 죽었으면 새로 생성
                try:
                    _driver.quit()
                except Exception:
                    pass
                _driver = None

        if _driver is None:
            print("[Chrome] 드라이버 시작 중...")
            _driver = _create_driver()
            print("[Chrome] 드라이버 준비 완료")

    return _driver


def _is_bad_title(text: str) -> bool:
    """제목으로 부적합한 텍스트 판별"""
    if text.startswith(("http://", "https://", "www.")):
        return True
    if text.count("/") >= 2 and "." in text:
        return True
    if len(text) <= 2:
        return True
    return False


def _extract_related(driver) -> list[str]:
    """연관 검색어 추출 (JS 실행)"""
    script = """
        const seen = new Set();
        const results = [];
        const selectors = ['.dg6jd', '.oatEtb', '.Q71vJc', '.s75CSd'];
        for (const sel of selectors) {
            document.querySelectorAll(sel).forEach(el => {
                const t = el.textContent.trim();
                if (t && t.length > 2 && !seen.has(t)) {
                    seen.add(t);
                    results.push(t);
                }
            });
            if (results.length > 0) break;
        }
        return results;
    """
    return driver.execute_script(script)


def get_google_titles(query: str) -> tuple[list[str], list[str]]:
    """
    구글 검색 결과 1페이지에서 제목 + 연관 검색어 반환

    :param query: 검색어
    :return: (제목 리스트, 연관 검색어 리스트)
    """
    driver = _get_driver()

    titles = []
    related = []

    try:
        # ── 1. 구글 검색 페이지 이동 ────────────────────────────
        encoded_query = query.replace(" ", "+")
        url = f"https://www.google.com/search?q={encoded_query}&hl=ko&gl=KR"
        driver.get(url)

        # ── 2. 검색 결과 로딩 대기 (최대 6초) ───────────────────
        WebDriverWait(driver, 6).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "h3 .LC20lb, #search h3"))
        )

        # ── 3. 광고 제목 수집 (제외용) ──────────────────────────
        ad_h3_texts = set()
        for ad_id in ["tads", "tadsb"]:
            try:
                ad_block = driver.find_element(By.ID, ad_id)
                for el in ad_block.find_elements(By.TAG_NAME, "h3"):
                    t = el.text.strip()
                    if t:
                        ad_h3_texts.add(t)
            except Exception:
                pass

        # ── 4. 제목 추출 (JS로 사이트링크·PAA 제외) ─────────────
        script = """
            const adTexts = arguments[0];
            const seen = new Set(adTexts);
            const results = [];

            document.querySelectorAll('#search h3 .LC20lb').forEach(function(span) {
                // 사이트링크 제외 (HiHjCd, o5PEGf, dG2XIf)
                if (span.closest('.HiHjCd') ||
                    span.closest('.o5PEGf') ||
                    span.closest('.dG2XIf')) return;
                // PAA(사람들이 자주 묻는 질문) 제외
                if (span.closest('.related-question-pair') ||
                    span.closest('.g-accordion-expander')) return;
                // 동영상 캐러셀 제외
                if (span.closest('.X5OiLe') ||
                    span.closest('g-scrolling-carousel')) return;

                const text = (span.textContent || '').trim();
                if (text.length > 2 && !seen.has(text)) {
                    seen.add(text);
                    results.push(text);
                }
            });
            return results;
        """
        js_titles = driver.execute_script(script, list(ad_h3_texts))
        titles = [t for t in js_titles if not _is_bad_title(t)]

        # 폴백: JS 결과가 없을 때
        if not titles:
            try:
                search_container = driver.find_element(By.ID, "search")
                for h3 in search_container.find_elements(By.TAG_NAME, "h3"):
                    text = h3.text.strip()
                    if not text or text in ad_h3_texts or _is_bad_title(text):
                        continue
                    try:
                        h3.find_element(By.XPATH, "./ancestor::a")
                        titles.append(text)
                    except Exception:
                        pass
            except Exception:
                pass

        # ── 5. 연관 검색어 추출 ──────────────────────────────────
        related = _extract_related(driver)

        # 없으면 스크롤 후 재시도
        if not related:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(0.4)
            related = _extract_related(driver)

    except Exception as e:
        print(f"[스크래퍼 오류] {e}")
        # 오류 발생 시 드라이버 초기화 (다음 요청에서 재생성)
        global _driver
        try:
            driver.quit()
        except Exception:
            pass
        _driver = None

    return titles, related


def shutdown_driver():
    """서버 종료 시 드라이버 정리"""
    global _driver
    with _driver_lock:
        if _driver is not None:
            try:
                _driver.quit()
            except Exception:
                pass
            _driver = None
            print("[Chrome] 드라이버 종료")


# ── 단독 실행 테스트 ─────────────────────────────────────────────
def main():
    print("=" * 50)
    print("  구글 검색 결과 제목 스크래퍼")
    print("=" * 50)
    query = input("검색어를 입력하세요: ").strip()

    if not query:
        print("검색어가 비어 있습니다.")
        return

    print(f"\n[{query}] 검색 중...")
    titles, related = get_google_titles(query)

    if not titles:
        print("검색 결과 제목을 가져오지 못했습니다.")
    else:
        print(f"\n총 {len(titles)}개 제목:\n")
        for i, title in enumerate(titles, 1):
            print(f"{i}. {title}")

    if related:
        print(f"\n연관 검색어 ({len(related)}개):\n")
        for i, kw in enumerate(related, 1):
            print(f"{i}. {kw}")

    shutdown_driver()


if __name__ == "__main__":
    main()
