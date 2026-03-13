"""
SEO 제목 생성기
────────────────────────────────────────────────
입력 데이터:
  ① 구글 상위 노출 제목 (스크래핑 결과)
  ② 연관 검색어 (구글 자동완성/하단 추천)

목표: 두 데이터를 조합 → 핵심 키워드 검색 시 3위 이내 노출 가능한 제목 생성
────────────────────────────────────────────────
SEO 원칙:
  - 핵심 키워드를 제목 맨 앞에 배치 (가장 중요)
  - 20~35자 최적 길이
  - 연관 검색어 포함 → 롱테일 키워드 커버
  - 상위 노출 제목 패턴 반영 → 검증된 구조 사용
  - CTR 향상 단어 포함
"""

import re
from collections import Counter
from datetime import datetime

CURRENT_YEAR = datetime.now().year

# 범용 CTR 향상 단어 (도메인 무관)
POWER_WORDS = [
    "방법", "총정리", "완벽", "핵심", "가이드", "정리", "쉽게",
    "알아보기", "입문", "기초", "활용", "추천", "비교", "최신",
    "한번에", "빠르게", "필수", "자세히",
]

STOPWORDS = {
    "및", "의", "을", "를", "이", "가", "은", "는", "에서",
    "으로", "로", "에", "도", "만", "와", "과", "부터",
    "까지", "입니다", "합니다", "있습니다",
    "<", ">", "|", "-", "·", "...", "…",
}


# ────────────────────────────────────────────────────────────
# 내부 유틸
# ────────────────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    tokens = re.split(r"[\s\|\-\<\>\·\/\,]+", text)
    return [t.strip() for t in tokens
            if t.strip() and t.strip() not in STOPWORDS and len(t.strip()) >= 2]


def _remove_keyword(text: str, keyword: str) -> str:
    """텍스트에서 핵심 키워드(및 공백 변형) 제거 → 순수 수식어만 추출"""
    result = text
    # 공백 없는 형태 제거
    result = result.replace(keyword.replace(" ", ""), "")
    # 공백 있는 형태 제거
    result = result.replace(keyword, "")
    return result.strip()


def _extract_top_modifiers(keyword: str, titles: list[str]) -> list[str]:
    """
    ① 구글 상위 노출 제목에서 수식어 추출
    - 핵심 키워드 제거 후 남은 단어를 빈도 분석
    - 빈도 높을수록 상위 노출에 검증된 단어
    """
    token_counter: Counter = Counter()
    kw_tokens = set(_tokenize(keyword))

    for title in titles:
        tokens = _tokenize(title)
        for t in tokens:
            if t not in kw_tokens and len(t) >= 2:
                token_counter[t] += 1

    # 빈도순 정렬, 최대 15개
    return [word for word, _ in token_counter.most_common(15)]


def _extract_related_suffixes(keyword: str, related: list[str]) -> list[str]:
    """
    ② 연관 검색어에서 핵심 키워드를 뺀 '차별화 suffix' 추출
    예) keyword='바이브코딩', related='바이브코딩 하는 방법' → '하는 방법'
    """
    seen = set()
    suffixes = []

    for r in related:
        r = r.strip()
        if not r:
            continue

        # 연관 검색어 자체를 먼저 저장 (원본)
        if r not in seen:
            seen.add(r)

        # suffix 추출
        suffix = _remove_keyword(r, keyword)
        # 토큰 단위로도 시도
        if not suffix:
            suffix = r

        suffix = suffix.strip(" ,·|-")
        if suffix and len(suffix) >= 2 and suffix not in seen:
            seen.add(suffix)
            suffixes.append(suffix)

    return suffixes


def _score_title(title: str, keyword: str, related: list[str]) -> float:
    """
    SEO 점수 계산 (100점 만점 기준)

    점수 요소:
      ① 키워드 위치     (최대 40점) — 앞에 있을수록 높은 점수
      ② 제목 길이       (최대 20점) — 20~35자 최적
      ③ CTR 향상 단어   (최대 15점) — 클릭률 높이는 단어
      ④ 연관 검색어 포함 (최대 20점) — 롱테일 커버
      ⑤ 연도 포함 보너스 (+5점)
      ⑥ 중복 단어 페널티 (-5점)
    """
    score = 0.0
    kw_clean = keyword.replace(" ", "")
    title_no_space = title.replace(" ", "")
    title_len = len(title)

    # ① 키워드 위치 (최대 40점)
    if title_no_space.startswith(kw_clean):
        score += 40   # 맨 앞 — 최상
    elif title_no_space[:len(kw_clean) + 4].startswith(kw_clean[:3]):
        score += 20   # 앞부분 근처
    elif kw_clean in title_no_space:
        score += 8    # 중간/뒤

    # ② 제목 길이 (최대 20점)
    if 20 <= title_len <= 32:
        score += 20
    elif 15 <= title_len <= 40:
        score += 12
    elif title_len < 10 or title_len > 55:
        score -= 5

    # ③ CTR 향상 단어 (최대 15점, 단어당 5점)
    pw_hit = sum(1 for pw in POWER_WORDS if pw in title)
    score += min(pw_hit * 5, 15)

    # ④ 연관 검색어 포함 (최대 20점, 검색어당 5점)
    rel_hit = 0
    for r in related:
        r_tokens = _tokenize(r)
        if any(t in title for t in r_tokens if len(t) >= 2):
            rel_hit += 1
    score += min(rel_hit * 5, 20)

    # ⑤ 연도 포함 보너스
    if str(CURRENT_YEAR) in title:
        score += 5

    # ⑥ 중복 단어 페널티
    tokens = _tokenize(title)
    if len(tokens) != len(set(tokens)):
        score -= 5

    return round(score, 1)


# ────────────────────────────────────────────────────────────
# 메인 함수
# ────────────────────────────────────────────────────────────

def generate_seo_titles(keyword: str, titles: list[str], related: list[str]) -> list[dict]:
    """
    SEO 최적화 제목 생성

    ① 구글 상위 제목  → 검증된 수식어 추출
    ② 연관 검색어     → 실제 검색 의도(suffix) 추출
    → 두 데이터 조합 → 핵심 키워드 3위 이내 목표 제목 10개 반환
    """
    # 데이터 추출
    top_modifiers   = _extract_top_modifiers(keyword, titles)      # ① 상위 제목 수식어
    related_suffixes = _extract_related_suffixes(keyword, related)  # ② 연관 검색어 suffix

    results: list[dict] = []
    seen: set[str] = set()

    def add(title: str, strategy: str):
        t = title.strip()
        if t and t not in seen and len(t) >= 6:
            seen.add(t)
            results.append({
                "title": t,
                "score": _score_title(t, keyword, related),
                "strategy": strategy,
            })

    # ══ 전략 A: 연관 검색어 직접 사용 ════════════════════════════
    # 연관 검색어 = 사람들이 실제로 검색하는 쿼리 → SEO 가장 강력
    kw_clean = keyword.replace(" ", "")
    for r in related:
        r = r.strip()
        if not r:
            continue
        r_no_space = r.replace(" ", "")
        if r_no_space.startswith(kw_clean):
            # 이미 키워드로 시작하면 그대로 사용
            add(r, "연관검색어 직접")
        else:
            # 키워드가 앞에 없으면 붙여줌
            add(f"{keyword} {r}", "연관검색어 앞배치")

    # ══ 전략 B: 연관 suffix + 상위 제목 수식어 조합 ══════════════
    # 연관 검색어의 핵심 부분 + 상위 노출 검증된 단어 결합
    for suffix in related_suffixes[:5]:
        for mod in top_modifiers[:4]:
            candidate = f"{keyword} {suffix} {mod}"
            add(candidate, "연관+상위패턴 복합")

    # ══ 전략 C: 키워드 + 상위 제목 수식어 ═══════════════════════
    # 구글 상위 노출 제목에서 검증된 수식어를 그대로 활용
    for mod in top_modifiers[:8]:
        add(f"{keyword} {mod}", "상위노출 패턴")
    # 수식어 2개 조합
    for i in range(min(4, len(top_modifiers) - 1)):
        add(f"{keyword} {top_modifiers[i]} {top_modifiers[i+1]}", "상위노출 복합")

    # ══ 전략 D: 연관 suffix 2개 조합 ════════════════════════════
    # 두 연관 검색어의 suffix를 합쳐서 롱테일 커버
    for i in range(min(4, len(related_suffixes) - 1)):
        s1 = related_suffixes[i]
        s2 = related_suffixes[i + 1]
        if s1 != s2:
            add(f"{keyword} {s1} {s2}", "연관 복합")

    # ══ 전략 E: 연도 + 키워드 + 상위 수식어 ═════════════════════
    # 최신성 강조 → 검색 노출 유리
    for mod in (top_modifiers[:3] or ["총정리", "가이드", "정리"]):
        add(f"{CURRENT_YEAR} {keyword} {mod}", "연도+상위패턴")
    # 연도 + 연관 suffix
    for suffix in related_suffixes[:2]:
        add(f"{CURRENT_YEAR} {keyword} {suffix}", "연도+연관")

    # ══ 전략 F: 상위 노출 제목 직접 변형 ════════════════════════
    # 이미 상위 노출 중인 제목 → 키워드를 앞에 붙여 변형
    for title in titles[:5]:
        t_clean = title.replace(" ", "")
        if not t_clean.startswith(kw_clean):
            add(f"{keyword} | {title}", "상위노출 변형")

    # ══ 점수 정렬 후 상위 10개 반환 ══════════════════════════════
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:10]
