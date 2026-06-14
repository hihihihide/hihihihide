# 苫小牧市議会 議事録スクレイパー

苫小牧市議会の公式ウェブサイトから全ての議事録・会議録を収集するスクレイパーです。

## 収集元

| ソース | URL | 内容 |
|--------|-----|------|
| 公式サイト | https://www.city.tomakomai.hokkaido.jp/gikai/ | 議会報告PDF・各種資料 |
| インターネット中継 | https://tomakomai-city.stream.jfit.co.jp/ | 会議映像・会議録リンク |
| 会議録検索システム | https://ssp.kaigiroku.net/tenant/tomakomai/ | 議事録全文・会議録PDF（DiscussNetPremium） |

## セットアップ

```bash
pip install -r requirements.txt
```

## 使い方

### リンク収集のみ（最速）

```bash
python scraper.py --output-dir data
```

### PDFダウンロードあり

```bash
python scraper.py --output-dir data --pdf
```

### PDF + テキスト抽出

```bash
python scraper.py --output-dir data --pdf --text
```

### 会議録HTML + テキスト抽出 (kaigiroku.net)

```bash
python scraper.py --output-dir data --minutes
```

### オプション一覧

| オプション | 説明 | デフォルト |
|------------|------|------------|
| `--output-dir DIR` | 出力先ディレクトリ | `data` |
| `--pdf` | PDFをダウンロードする | なし |
| `--text` | PDFからテキストを抽出する | なし |
| `--skip-stream` | 中継サイトをスキップ | なし |
| `--skip-kaigiroku` | 会議録検索システムをスキップ | なし |
| `--minutes` | 会議録HTMLをダウンロードしてテキスト抽出（kaigiroku.net） | なし |
| `--delay SEC` | リクエスト間隔（秒） | `1.0` |

## 出力ファイル

```
data/
├── records.json     # 全収集レコード（URL・タイトル・ローカルパス）
├── pages.json       # クロールしたHTMLページ一覧
├── pdfs/            # ダウンロードしたPDF（--pdf 使用時）
├── minutes/         # ダウンロードした会議録HTML（--minutes 使用時）
└── texts/           # 抽出したテキスト（--text / --minutes 使用時）
```

## 注意事項

- 苫小牧市公式サイトは**日本国内のIPアドレス**からのアクセスを推奨します
- 海外のサーバー（クラウド環境等）からは403エラーになる場合があります
- サーバー負荷軽減のため、`--delay` オプションで適切な間隔を設定してください（推奨: 1秒以上）
- 収集した議事録は研究・公益目的での利用を想定しています
