"""
苫小牧市議会 議事録スクレイパー

苫小牧市議会の公式サイト・インターネット中継システム・会議録検索システムから
全ての議事録・会議録を収集・ダウンロードします。

収集元:
    - https://www.city.tomakomai.hokkaido.jp/gikai/  (公式サイト)
    - https://tomakomai-city.stream.jfit.co.jp/       (インターネット中継)
    - https://ssp.kaigiroku.net/tenant/tomakomai/    (会議録検索システム)

Usage:
    python scraper.py [--output-dir data] [--pdf] [--text]

注意:
    各サイトは日本国内からのアクセスを想定しています。
    海外のIPアドレスや一部のクラウド環境からは403エラーが返される場合があります。
"""

import argparse
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlencode

import requests
from bs4 import BeautifulSoup

# --- 定数 ---
BASE_URL = "https://www.city.tomakomai.hokkaido.jp"
GIKAI_URL = f"{BASE_URL}/gikai/"
STREAM_BASE = "https://tomakomai-city.stream.jfit.co.jp"
GIKAI_ID = "207"

# 会議録検索システム (ssp.kaigiroku.net / DiscussNetPremium)
KAIGIROKU_BASE = "https://ssp.kaigiroku.net/tenant/tomakomai"
KAIGIROKU_PAGES = [
    "/SpTop.html",
    "/pg/index.html",
    "/SpMinuteBrowse.html",
    "/SpSearch.html",
    "/index.html",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# 市議会サイトの既知ページ
KNOWN_COUNCIL_PAGES = [
    "/gikai/",
    "/gikai/katsudo/",
    "/gikai/katsudo/houkoku.html",        # 議会報告
    "/gikai/katsudo/gikainittei.html",     # 議会日程
    "/gikai/katsudo/shinginokekka.html",   # 審議の結果
    "/gikai/katsudo/nenpou.html",          # 議会年報
    "/gikai/katsudo/gian.html",            # 議会提出議案
    "/gikai/katsudo/yoboikensyo-ketugi.html",  # 要望意見書・決議
    "/gikai/shokai/",
    "/gikai/shokai/giinmeibo.html",        # 議員名簿
    "/gikai/shokai/iinkai.html",           # 委員会別名簿
]

# jfit.co.jp で使われるテンプレート
JFIT_TEMPLATES = [
    ("gikai_list", {}),               # 会議名一覧
    ("gikai_result", {"gikai_id": GIKAI_ID}),  # 会議検索
    ("speaker_list", {}),             # 議員一覧
    ("speaker_result", {"gikai_id": GIKAI_ID}),  # 議員検索
    ("keyword_search", {}),           # キーワード検索
]


# --- ユーティリティ ---

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def fetch(session: requests.Session, url: str, delay: float = 1.0, params: dict = None) -> requests.Response | None:
    time.sleep(delay)
    try:
        r = session.get(url, params=params, timeout=30)
        if r.status_code == 200:
            return r
        print(f"  [{r.status_code}] {url}")
        return None
    except Exception as e:
        print(f"  [ERROR] {url}: {e}")
        return None


def get_encoding(r: requests.Response) -> str:
    if r.encoding and r.encoding.lower() not in ("iso-8859-1", "latin-1"):
        return r.encoding
    return r.apparent_encoding or "utf-8"


def parse_html(r: requests.Response) -> BeautifulSoup:
    r.encoding = get_encoding(r)
    return BeautifulSoup(r.text, "lxml")


def extract_links(soup: BeautifulSoup, base_url: str) -> list[dict]:
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue
        full_url = urljoin(base_url, href)
        text = a.get_text(strip=True)
        links.append({"url": full_url, "text": text})
    return links


def is_council_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc == "www.city.tomakomai.hokkaido.jp":
        return parsed.path.startswith("/gikai/") or parsed.path.startswith("/files/")
    return False


def is_kaigiroku_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc == "ssp.kaigiroku.net" and "/tenant/tomakomai" in parsed.path


def is_pdf(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".pdf")


def safe_filename(url: str) -> str:
    parsed = urlparse(url)
    name = (parsed.netloc + parsed.path).replace("/", "_").lstrip("_")
    name = re.sub(r"[^\w\-.]", "_", name)
    return name[:200]


def extract_title(soup: BeautifulSoup) -> str:
    t = soup.find("title")
    return t.get_text(strip=True) if t else ""


# --- クロール ---

def crawl_council_site(session: requests.Session, output_dir: Path) -> list[dict]:
    """公式市議会サイトをクロールしてPDF/ページリンクを収集する。"""
    print("\n=== 公式サイトのクロール ===")
    visited: set[str] = set()
    queue: list[str] = [urljoin(BASE_URL, p) for p in KNOWN_COUNCIL_PAGES]
    pdf_records: list[dict] = []
    page_records: list[dict] = []

    while queue:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        if is_pdf(url):
            if url not in {r["url"] for r in pdf_records}:
                pdf_records.append({"url": url, "source": "crawl-seed"})
            continue

        print(f"  取得: {url}")
        r = fetch(session, url, delay=1.0)
        if r is None:
            continue

        soup = parse_html(r)
        title = extract_title(soup)
        page_records.append({"url": url, "title": title})

        for link in extract_links(soup, url):
            lurl = link["url"]
            if lurl in visited:
                continue
            if is_pdf(lurl) and is_council_url(lurl):
                if lurl not in {r["url"] for r in pdf_records}:
                    pdf_records.append({"url": lurl, "text": link["text"], "source": url})
                    print(f"    [PDF] {link['text']} → {lurl}")
            elif is_council_url(lurl) and lurl not in queue:
                queue.append(lurl)

    (output_dir / "pages.json").write_text(
        json.dumps(page_records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  ページ: {len(page_records)}件, PDF: {len(pdf_records)}件")
    return pdf_records


def crawl_kaigiroku_site(session: requests.Session) -> list[dict]:
    """会議録検索システム (ssp.kaigiroku.net) から会議録・PDFリンクを収集する。"""
    print("\n=== 会議録検索システムのクロール (ssp.kaigiroku.net) ===")
    records: list[dict] = []
    visited: set[str] = set()
    queue: list[str] = [KAIGIROKU_BASE + p for p in KAIGIROKU_PAGES]

    while queue:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        print(f"  取得: {url}")
        r = fetch(session, url, delay=1.0)
        if r is None:
            continue

        soup = parse_html(r)

        for link in extract_links(soup, url):
            lurl = link["url"]
            if lurl in visited:
                continue

            if is_pdf(lurl) and is_kaigiroku_url(lurl):
                entry = {"url": lurl, "text": link["text"], "source": "kaigiroku/pdf"}
                if lurl not in {rec["url"] for rec in records}:
                    records.append(entry)
                    print(f"    [PDF] {link['text']} → {lurl}")

            elif is_kaigiroku_url(lurl):
                # 会議録表示・検索ページを収集
                parsed = urlparse(lurl)
                interesting = any(kw in parsed.path for kw in (
                    "SpMinuteView", "SpMinuteBrowse", "MinuteView",
                    "SpSearch", "SpTop", "index",
                ))
                if interesting and lurl not in queue:
                    if any(kw in lurl for kw in ("View", "Browse", "Search")):
                        entry = {"url": lurl, "text": link["text"], "source": "kaigiroku/page"}
                        if lurl not in {rec["url"] for rec in records}:
                            records.append(entry)
                            print(f"    [PAGE] {link['text']} → {lurl}")
                    queue.append(lurl)

    print(f"  会議録検索システムから: {len(records)}件")
    return records


def crawl_stream_site(session: requests.Session) -> list[dict]:
    """インターネット中継サイトから会議録リンクを収集する。"""
    print("\n=== インターネット中継サイトのクロール ===")
    records: list[dict] = []

    for tpl, extra_params in JFIT_TEMPLATES:
        params = {"tpl": tpl, **extra_params}
        url = STREAM_BASE + "/?" + urlencode(params)
        print(f"  テンプレート: {tpl}")
        r = fetch(session, STREAM_BASE, delay=1.0, params=params)
        if r is None:
            continue

        soup = parse_html(r)
        for link in extract_links(soup, url):
            lurl = link["url"]
            if is_pdf(lurl) or any(k in lurl for k in ("gijiroku", "kaigiroku", "voices")):
                entry = {"url": lurl, "text": link["text"], "source": f"jfit/{tpl}"}
                if lurl not in {r["url"] for r in records}:
                    records.append(entry)
                    print(f"    [FOUND] {link['text']} → {lurl}")

    print(f"  中継サイトから: {len(records)}件")
    return records


# --- ダウンロード ---

def download_pdf(session: requests.Session, url: str, dest: Path) -> bool:
    if dest.exists():
        return True
    r = fetch(session, url, delay=0.5)
    if r is None:
        return False
    dest.write_bytes(r.content)
    print(f"  [DL] {dest.name} ({len(r.content):,} bytes)")
    return True


def extract_text_from_pdf(pdf_path: Path) -> str:
    try:
        from pdfminer.high_level import extract_text
        return extract_text(str(pdf_path))
    except Exception as e:
        print(f"  [PDF ERROR] {pdf_path.name}: {e}")
        return ""


def download_minutes_page(session: requests.Session, url: str, dest: Path) -> bool:
    if dest.exists():
        return True
    r = fetch(session, url, delay=1.0)
    if r is None:
        return False
    r.encoding = get_encoding(r)
    dest.write_text(r.text, encoding="utf-8")
    print(f"  [DL] {dest.name} ({len(r.text):,} chars)")
    return True


def extract_text_from_minutes_html(html_path: Path) -> str:
    text = html_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(text, "lxml")
    # kaigiroku.net の会議録本文は div.sp-minutes-body 等に格納されている場合が多い
    for selector in ("div.sp-minutes-body", "div#minutes-body", "div.minutes", "article", "main"):
        body = soup.select_one(selector)
        if body:
            return body.get_text(separator="\n", strip=True)
    # フォールバック: body タグ全体からスクリプト・スタイルを除いて取得
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


# --- メイン ---

def main():
    parser = argparse.ArgumentParser(description="苫小牧市議会 議事録スクレイパー")
    parser.add_argument("--output-dir", default="data", help="出力ディレクトリ (default: data)")
    parser.add_argument("--pdf", action="store_true", help="PDFをダウンロードする")
    parser.add_argument("--text", action="store_true", help="PDFからテキストを抽出する")
    parser.add_argument("--minutes", action="store_true", help="会議録HTMLをダウンロードしてテキスト抽出する (kaigiroku.net)")
    parser.add_argument("--skip-stream", action="store_true", help="中継サイトをスキップ")
    parser.add_argument("--skip-kaigiroku", action="store_true", help="会議録検索システムをスキップ")
    parser.add_argument("--delay", type=float, default=1.0, help="リクエスト間隔(秒) (default: 1.0)")
    args = parser.parse_args()

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    session = make_session()

    # 接続確認
    print("接続確認中...")
    for check_url, label in [
        (GIKAI_URL, "公式サイト"),
        (KAIGIROKU_BASE + "/SpTop.html", "会議録検索システム"),
    ]:
        r = fetch(session, check_url, delay=0)
        if r is None:
            print(
                f"\n[WARNING] {label} ({check_url}) への接続に失敗しました。\n"
                "  - 日本国内のIP、またはVPN経由で実行してください。\n"
                "  - スクレイパーは継続しますが、結果が少なくなる場合があります。\n"
            )
        else:
            print(f"  [{label}] 接続成功。")

    # クロール
    all_records: list[dict] = []
    all_records.extend(crawl_council_site(session, out))
    if not args.skip_stream:
        all_records.extend(crawl_stream_site(session))
    if not args.skip_kaigiroku:
        all_records.extend(crawl_kaigiroku_site(session))

    # 重複除去
    seen: set[str] = set()
    unique: list[dict] = []
    for rec in all_records:
        if rec["url"] not in seen:
            seen.add(rec["url"])
            unique.append(rec)

    records_file = out / "records.json"
    records_file.write_text(
        json.dumps(unique, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n収集レコード: {len(unique)}件 → {records_file}")

    # PDFダウンロード
    if args.pdf or args.text:
        pdf_dir = out / "pdfs"
        pdf_dir.mkdir(exist_ok=True)
        pdf_items = [r for r in unique if is_pdf(r["url"])]
        print(f"\n=== PDFダウンロード ({len(pdf_items)}件) ===")

        downloaded: list[dict] = []
        for rec in pdf_items:
            fname = safe_filename(rec["url"])
            if not fname.endswith(".pdf"):
                fname += ".pdf"
            dest = pdf_dir / fname
            if download_pdf(session, rec["url"], dest):
                rec["local_path"] = str(dest)
                downloaded.append(rec)

        print(f"ダウンロード完了: {len(downloaded)}件")

        # テキスト抽出
        if args.text and downloaded:
            text_dir = out / "texts"
            text_dir.mkdir(exist_ok=True)
            print(f"\n=== テキスト抽出 ({len(downloaded)}件) ===")
            for rec in downloaded:
                pdf_path = Path(rec["local_path"])
                text = extract_text_from_pdf(pdf_path)
                if text.strip():
                    text_path = text_dir / (pdf_path.stem + ".txt")
                    text_path.write_text(text, encoding="utf-8")
                    rec["text_path"] = str(text_path)
                    print(f"  [TXT] {text_path.name} ({len(text):,} chars)")

        # 最終保存
        records_file.write_text(
            json.dumps(unique, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # 会議録HTMLダウンロード (kaigiroku.net)
    if args.minutes:
        minutes_dir = out / "minutes"
        minutes_dir.mkdir(exist_ok=True)
        text_dir = out / "texts"
        text_dir.mkdir(exist_ok=True)
        minute_items = [r for r in unique if r.get("source") == "kaigiroku/page"]
        print(f"\n=== 会議録HTMLダウンロード ({len(minute_items)}件) ===")

        for rec in minute_items:
            fname = safe_filename(rec["url"]) + ".html"
            dest = minutes_dir / fname
            if download_minutes_page(session, rec["url"], dest):
                rec["minutes_path"] = str(dest)
                text = extract_text_from_minutes_html(dest)
                if text.strip():
                    text_path = text_dir / (dest.stem + ".txt")
                    text_path.write_text(text, encoding="utf-8")
                    rec["text_path"] = str(text_path)
                    print(f"  [TXT] {text_path.name} ({len(text):,} chars)")

        print(f"会議録ダウンロード完了: {len(minute_items)}件")
        records_file.write_text(
            json.dumps(unique, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    print("\n完了。")


if __name__ == "__main__":
    main()
