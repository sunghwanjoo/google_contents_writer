import os
import re
import json
import threading
import webbrowser
import traceback
import secrets
from datetime import datetime

import anthropic
from dotenv import load_dotenv
from flask import Flask, request, jsonify, Response, stream_with_context, session, redirect, url_for
from flask_cors import CORS
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

from google_scraper import get_google_titles, shutdown_driver
from title_generator import _score_title

# ── 환경변수 로드 (.env 파일) ─────────────────────────────────
load_dotenv()

app = Flask(__name__, static_folder=".", static_url_path="")
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(16))
CORS(app, supports_credentials=True)

app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True

# ── Google OAuth 설정 ─────────────────────────────────────────
GOOGLE_CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
SCOPES = ["https://www.googleapis.com/auth/blogger"]
REDIRECT_URI = "http://localhost:5000/oauth/callback"

os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"  # 로컬 http 허용


def _get_blogger_service():
    """세션 토큰으로 Blogger API 서비스 객체 반환"""
    token_data = session.get("google_token")
    if not token_data:
        return None
    creds = Credentials(
        token=token_data["token"],
        refresh_token=token_data.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=SCOPES,
    )
    return build("blogger", "v3", credentials=creds)


# ────────────────────────────────────────────────────────────
# OAuth 라우트
# ────────────────────────────────────────────────────────────

@app.route("/oauth/login")
def oauth_login():
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return jsonify({"error": ".env 파일에 GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET을 설정해주세요."}), 500

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [REDIRECT_URI],
            }
        },
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    session["oauth_state"] = state
    session["oauth_code_verifier"] = getattr(flow, "code_verifier", None)
    return redirect(auth_url)


@app.route("/oauth/callback")
def oauth_callback():
    try:
        code = request.args.get("code")
        print(f"[콜백] code={'있음' if code else '없음'}, args={list(request.args.keys())}")
        if not code:
            return f"<pre>code 없음. args={dict(request.args)}</pre>", 400

        import urllib.request as _ureq
        import urllib.parse as _uparse
        import json as _json

        code_verifier = session.get("oauth_code_verifier")
        token_params = {
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        }
        if code_verifier:
            token_params["code_verifier"] = code_verifier
        data = _uparse.urlencode(token_params).encode()

        req = _ureq.Request("https://oauth2.googleapis.com/token", data=data, method="POST")
        try:
            with _ureq.urlopen(req) as resp:
                token_data = _json.loads(resp.read())
        except _ureq.HTTPError as http_err:
            body = http_err.read().decode()
            print(f"[토큰 교환 오류] {http_err.code}: {body}")
            return f"<pre>토큰 교환 실패 ({http_err.code}):\n{body}</pre>", 400

        if "error" in token_data:
            return f"<pre>토큰 오류: {token_data}</pre>", 400

        print(f"[콜백] 토큰 수신 성공")
        session["google_token"] = {
            "token": token_data.get("access_token"),
            "refresh_token": token_data.get("refresh_token"),
        }
        return redirect("/?login=success")
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[OAuth 콜백 오류]\n{tb}")
        return f"<pre style='color:red'>{tb}</pre>", 500


@app.route("/oauth/logout")
def oauth_logout():
    session.pop("google_token", None)
    return redirect("/")


@app.route("/oauth/status")
def oauth_status():
    """로그인 여부 확인"""
    logged_in = "google_token" in session
    return jsonify({"logged_in": logged_in})


# ────────────────────────────────────────────────────────────
# Blogger API 라우트
# ────────────────────────────────────────────────────────────

@app.route("/api/blogs")
def get_blogs():
    """내 블로그 목록 반환"""
    service = _get_blogger_service()
    if not service:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    try:
        result = service.blogs().listByUser(userId="self").execute()
        blogs = [{"id": b["id"], "name": b["name"], "url": b["url"]}
                 for b in result.get("items", [])]
        return jsonify({"blogs": blogs})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/publish", methods=["POST"])
def publish_post():
    """Blogger에 포스트 예약 발행"""
    service = _get_blogger_service()
    if not service:
        return jsonify({"error": "로그인이 필요합니다."}), 401

    data       = request.json
    blog_id    = data.get("blogId", "")
    title      = data.get("title", "")
    content    = data.get("content", "")
    publish_at = data.get("publishAt", "")  # ISO8601: 2026-03-15T09:00:00+09:00

    if not blog_id or not title or not content:
        return jsonify({"error": "blogId, title, content는 필수입니다."}), 400

    # 마크다운 → HTML 간단 변환
    html_content = _md_to_html(content)

    body = {
        "title": title,
        "content": html_content,
    }

    try:
        if publish_at:
            # 예약 발행: isDraft=false + publishDate 설정
            result = service.posts().insert(
                blogId=blog_id,
                body={**body, "published": publish_at},
                isDraft=False,
            ).execute()
        else:
            # 즉시 발행
            result = service.posts().insert(
                blogId=blog_id,
                body=body,
                isDraft=False,
            ).execute()

        return jsonify({
            "success": True,
            "url": result.get("url", ""),
            "postId": result.get("id", ""),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _md_to_html(md: str) -> str:
    """마크다운 → HTML 기본 변환 (Blogger용)"""
    lines = md.split("\n")
    html_lines = []
    for line in lines:
        if line.startswith("## "):
            html_lines.append(f"<h2>{line[3:].strip()}</h2>")
        elif line.startswith("# "):
            html_lines.append(f"<h1>{line[2:].strip()}</h1>")
        elif line.startswith("### "):
            html_lines.append(f"<h3>{line[4:].strip()}</h3>")
        elif line.strip() == "":
            html_lines.append("<br>")
        else:
            # 굵게 **text**
            line = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
            html_lines.append(f"<p>{line}</p>")
    return "\n".join(html_lines)


# ────────────────────────────────────────────────────────────
# Claude API — SEO 제목 5개 생성
# ────────────────────────────────────────────────────────────

def _generate_seo_titles_ai(keyword: str, titles: list[str], related: list[str]) -> list[dict]:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return []

    titles_text  = "\n".join(f"- {t}" for t in titles[:10])
    related_text = "\n".join(f"- {r}" for r in related[:10])

    prompt = f"""당신은 한국어 구글 SEO 전문가입니다.
아래 데이터를 분석해서 '{keyword}' 키워드로 구글 검색 1~3위에 노출될 수 있는 블로그 제목 5개를 생성해주세요.

[핵심 키워드]
{keyword}

[현재 구글 상위 노출 중인 제목 (경쟁 분석용)]
{titles_text}

[연관 검색어 (사람들이 실제로 검색하는 쿼리)]
{related_text}

[제목 생성 전략]
1. 핵심 키워드 '{keyword}'를 반드시 제목 맨 앞에 배치
2. 연관 검색어를 분석해 사람들의 실제 검색 의도를 파악하고 제목에 반영
3. 상위 노출 제목의 효과적인 패턴(구조, 수식어)을 참고해 더 클릭률 높게 변형
4. 제목 길이: 20~35자 (SEO 최적 범위)
5. 5개의 제목은 각각 다른 전략 사용:
   - 1번: 연관 검색어 직접 활용형
   - 2번: 상위 노출 패턴 변형형
   - 3번: 정보 총정리형
   - 4번: 질문·해결형
   - 5번: 연도+최신정보형

[출력 규칙]
JSON 배열만 출력 (앞뒤 설명 없이):
["제목1", "제목2", "제목3", "제목4", "제목5"]"""

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}]
    )

    text = message.content[0].text.strip()
    match = re.search(r'\[.*?\]', text, re.DOTALL)
    if match:
        title_list = json.loads(match.group())
        return [
            {
                "title": t.strip(),
                "score": _score_title(t.strip(), keyword, related),
                "strategy": "AI SEO"
            }
            for t in title_list[:5] if t.strip()
        ]
    return []


# ────────────────────────────────────────────────────────────
# 기존 라우트
# ────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/scrape")
def scrape():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "검색어가 없습니다."}), 400

    try:
        titles, related = get_google_titles(q)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    seo_titles = []
    try:
        seo_titles = _generate_seo_titles_ai(q, titles, related)
        print(f"[SEO] {len(seo_titles)}개 생성됨")
    except Exception as e:
        print(f"[SEO 오류] {e}")
        traceback.print_exc()

    return jsonify({"titles": titles, "related": related, "seo_titles": seo_titles})


@app.route("/api/generate")
def generate_article():
    title       = request.args.get("title",   "").strip()
    keyword     = request.args.get("keyword", "").strip()
    related_raw = request.args.get("related", "")
    related     = [r.strip() for r in related_raw.split(",") if r.strip()][:6]

    if not title or not keyword:
        return jsonify({"error": "title과 keyword가 필요합니다."}), 400

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다."}), 500

    def stream():
        try:
            client = anthropic.Anthropic(api_key=api_key)
            related_str = ", ".join(related) if related else "없음"

            prompt = f"""당신은 한국어 SEO 전문 콘텐츠 작성가입니다.
다음 조건에 맞춰 구글 검색 결과 1~3위 노출을 목표로 한 SEO 최적화 블로그 글을 작성해주세요.

[제목]
{title}

[핵심 키워드]
{keyword}

[연관 키워드]
{related_str}

[작성 조건]
1. 글 길이: 1,500~2,500자 (한국어 기준)
2. 구조:
   - 도입부: 독자의 관심을 끄는 문장, 핵심 키워드 자연스럽게 포함 (2~3문장)
   - 본문: ## 소제목 3~4개, 각 소제목 아래 구체적 설명 및 실용 정보
   - 결론: 핵심 요약 + 독자 행동 유도 문구
3. SEO 규칙:
   - 핵심 키워드를 도입부, 각 섹션 첫 문단에 자연스럽게 포함
   - 연관 키워드를 본문에 2~3회 자연스럽게 삽입
   - 키워드 밀도 1~2% 유지
4. 문체: 친근하고 신뢰감 있는 한국어, 전문적이지만 이해하기 쉽게
5. 마크다운 형식으로 작성 (## 소제목 사용)

부가 설명 없이 블로그 글 본문만 작성해주세요."""

            with client.messages.stream(
                model="claude-haiku-4-5-20251001",
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}]
            ) as s:
                for chunk in s.text_stream:
                    yield f"data: {json.dumps(chunk)}\n\n"

            yield "data: [DONE]\n\n"

        except Exception as e:
            yield f"data: {json.dumps('[ERROR] ' + str(e))}\n\n"
            yield "data: [DONE]\n\n"

    return Response(
        stream_with_context(stream()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


# ────────────────────────────────────────────────────────────
# 서버 시작
# ────────────────────────────────────────────────────────────

import atexit
atexit.register(shutdown_driver)

if __name__ == "__main__":
    os.makedirs(".flask_session", exist_ok=True)
    is_local = os.environ.get("RAILWAY_ENVIRONMENT") is None
    port = int(os.environ.get("PORT", 5000))

    if is_local:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{port}")).start()
        print("=" * 45)
        print("  서버 시작 중... 브라우저가 자동으로 열립니다.")
        print("  종료하려면 이 창에서 Ctrl+C 를 누르세요.")
        print("=" * 45)

    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)
