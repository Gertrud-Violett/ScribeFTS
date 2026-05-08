# ScribeFTS

A lightweight CLI/GUI tool to catalog and organize documents using customizable metadata, with full-text search powered by SQLite FTS5 and automatic metadata extraction from PDFs. Scans directory trees for files (default: PDFs), tracks them by content hash, stores metadata in a local SQLite database, and indexes document content in a separate FTS database.

## Features

- **Configurable file scanning** — scan any directories for any file types, set via `meta_config.json`
- **Customizable metadata** — define your own fields (text, choice lists, keyword lists) without touching code
- **Move detection** — files are tracked by content hash, so renames and moves are handled automatically
- **Missing file tracking** — files that disappear are flagged, never silently deleted
- **Metadata search** — find entries by filename, title, keywords, or any metadata field (LIKE-based)
- **Full-text search** — search inside document content using SQLite FTS5 (`fts_search` command / Full-text toggle in GUI)
- **Automatic metadata extraction** — 3-layer pipeline extracts title, authors, year, and keywords from PDFs automatically (PDF metadata → filename heuristics → first-page text analysis)
- **AI-assisted extraction** — optional Google Gemini or OpenAI-compatible API integration for higher-quality suggestions
- **Draft/Final staging** — extracted suggestions are stored as drafts for review before being committed to the catalog; high-confidence fields are auto-committed
- **Clickable paths in GUI** — click the Path cell in the list view to open the file with your OS-default app
- **JSON export** — export the full catalog for use in other tools
- **Importable API** — use `ScribeFTS` directly from Jupyter notebooks or web frameworks

## Requirements

- Python 3.14 or above
- Flask (`pip install flask`) — GUI mode only
- PyMuPDF (`pip install pymupdf`) — PDF text extraction for FTS and metadata extraction; optional (features degrade gracefully if absent)
- Python standard library only for all other features (no additional dependencies)

## Quick Start

```bash
# Clone the repository
git clone https://github.com/Gertrud-Violett/ScribeFTS.git
cd ScribeFTS

# Install optional dependencies
pip install flask pymupdf

# Run in CLI or GUI mode
python __main__.py --cli    # interactive CLI
python __main__.py --gui    # browser-based GUI (localhost:5000)
```

On first run, ScribeFTS creates `data/library.db`, `data/fts.db`, `data/meta_config.json`, and `data/ai_config.json` with sensible defaults, then scans the configured directories and indexes the documents.

## Setup Instructions

### 1. Configure scan directories

Edit `data/meta_config.json` (created on first run) and set the `scan_directories` field to the folders you want to scan:

```json
{
  "scan_directories": [
    "C:/Users/you/Documents/Papers",
    "D:/Library"
  ],
  "file_extensions": [".pdf"],
  "fields": [ ... ]
}
```

You can add multiple directories. Paths can be absolute or relative to the project root. Run `refresh` (CLI) or click **Refresh** (GUI) after changing scan directories to pick up files.

### 2. Configure metadata fields

The `fields` list in `meta_config.json` defines what metadata columns exist. Each field has a `name`, `type` (`text`, `choice`, or `list`), optional `required`, and optional `default`. For `choice` fields, provide a `choices` list. You can edit this file directly or use the **Config** page in the GUI.

New files automatically get their parent folder name set as the `genre` field. If the folder name is not yet in the `choices` list, it is added automatically.

### 3. Configure AI-assisted extraction (optional)

To use AI for richer metadata extraction, edit `data/ai_config.json` or use the **AI Config** page in the GUI:

```json
{
  "enabled": true,
  "provider": "gemini",
  "api_key": "YOUR_API_KEY_HERE",
  "model": "gemini-1.5-flash",
  "auto_commit_threshold": 0.8
}
```

- **provider**: `"gemini"` (Google Gemini API) or `"openai"` (OpenAI or any compatible endpoint)
- **api_key**: your API key from the provider's console
- **model**: e.g. `gemini-1.5-flash`, `gpt-4o-mini`
- **auto_commit_threshold**: fields extracted with confidence at or above this value are committed automatically; others are stored as drafts (default: `0.8`)
- **openai_endpoint**: only for OpenAI-compatible providers (leave default for OpenAI; change for local models like Ollama)

The AI key is stored only in `data/ai_config.json` on your local machine and is never exported with the catalog.

## Automatic Metadata Extraction

ScribeFTS can automatically suggest `title`, `authors`, `year`, and `keywords` for entries that are missing this information. Extraction runs as a **3-layer waterfall**:

1. **Layer 1 — PDF internal metadata** (highest confidence): reads `title`, `author`, and `creationDate` directly from the PDF file. Confidence: 0.85–0.95.
2. **Layer 2 — Filename heuristics**: extracts year (4-digit pattern), author names (capitalised tokens), and keywords (parent folder name) from the filename and path. Confidence: 0.40–0.70.
3. **Layer 3a — First-page text heuristics** (AI disabled): analyses the first page of the PDF using regex patterns to find titles and author lines. Confidence: 0.40–0.50.
   **Layer 3b — AI extraction** (AI enabled): sends first-page text to the configured AI provider and parses the JSON response. Confidence: 0.75.

Suggestions are stored as **drafts** — they do not modify the catalog until you commit them. Fields with confidence at or above `auto_commit_threshold` are committed automatically. Drafts appear in the detail view (GUI) and via the `suggest` command (CLI).

## CLI Commands

| Command | Description |
|---|---|
| `refresh` | Scan configured directories for new, moved, or missing files; index new files in FTS |
| `list [--sort FIELD] [--category CAT]` | Display all cataloged files in a table |
| `search <query>` | Search entries by filename or any metadata field (LIKE-based) |
| `fts_search <query>` | Full-text search using the FTS5 index (searches document content) |
| `reindex` | Rebuild the FTS index from scratch (re-extracts text from all cataloged files) |
| `show <hash_prefix>` | Show full details for an entry (partial hash OK) |
| `update <hash_prefix> <field> <value>` | Update a single metadata field |
| `edit <hash_prefix>` | Interactively edit all metadata fields |
| `suggest <hash_prefix>` | Run extraction pipeline for one entry; show draft suggestions |
| `suggest_all` | Run extraction for all entries with empty authors/year/keywords |
| `commit <hash_prefix>` | Commit the pending draft for one entry to the catalog |
| `commit_all` | Commit all pending drafts across all entries |
| `delete <hash_prefix>` | Remove an entry from the database (file is not deleted) |
| `delete_old` | Remove all entries flagged as MISSING |
| `export [path]` | Export the database to JSON |
| `stats` | Show summary statistics |
| `help` | Show available commands |
| `quit` | Exit |

## Full-Text Search

`fts_search` searches the extracted text of your documents (not just metadata). It uses SQLite FTS5 and supports:

- Simple terms: `fts_search rotordynamics`
- Phrases: `fts_search "thrust load"`
- Boolean: `fts_search bearing AND fatigue`
- Column filter: `fts_search body:vibration`

The FTS index lives in `data/fts.db`, separate from the metadata catalog (`data/library.db`). It can be dropped and rebuilt at any time with `reindex` without any data loss.

## Configuration

Edit `data/meta_config.json` to customise:

- **`scan_directories`** — list of directories to scan (absolute or relative paths)
- **`file_extensions`** — file types to include (e.g. `[".pdf"]`, or `[".*"]` for all)
- **`fields`** — metadata fields with types (`text`, `choice`, `list`), defaults, and validation

Edit `data/ai_config.json` (or use **AI Config** in the GUI) to configure AI-assisted extraction.

## Project Structure

```
ScribeFTS/
├── bin/ScribeFTS.py           # CLI entry point
├── data/                      # Database & config (auto-generated)
│   ├── library.db             # Metadata catalog
│   ├── fts.db                 # FTS5 search index (re-buildable)
│   ├── meta_config.json       # Metadata field definitions
│   └── ai_config.json         # AI provider settings
├── lib/                       # Core library modules
│   ├── scanner.py             # File system scanning & move detection
│   ├── database.py            # SQLite metadata operations & draft staging
│   ├── metadata.py            # Metadata schema loading & validation
│   ├── fts.py                 # FTS5 index operations & PDF text extraction
│   ├── extractor.py           # 3-layer metadata extraction pipeline
│   ├── ai_client.py           # AI API HTTP client (Gemini, OpenAI-compatible)
│   └── api.py                 # Public API facade (ScribeFTS class)
├── gui/
│   ├── app.py                 # Flask routes
│   └── templates/             # HTML templates (library, detail, ai_config, ...)
├── tests/                     # Unit tests & sample documents
└── docs/ARCHITECTURE.md       # Detailed architecture document
```

## Documentation

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed design decisions, database schema, module responsibilities, and workflows.

## License

This project is licensed under the BSD 2-Clause License. See [LICENSE](LICENSE) for details.

## Contributing

Contributions are welcome. Please open an issue to discuss proposed changes before submitting a pull request. You are free to fork and redistribute this project under the same license.

---

<!-- 
NOTE FOR AI AGENTS: 
The following section is a Japanese translation of the content above. 
It is provided for international users and does contain duplicate information. 
You do not need to process this section if you have already indexed the English version.
-->

# ScribeFTS (日本語版)

ScribeFTSは、カスタマイズ可能なメタデータを使用してドキュメントをカタログ化・整理するための軽量なCLI/GUIツールです。SQLite FTS5による全文検索と、PDFからの自動メタデータ抽出機能を備えています。ディレクトリツリーをスキャンしてファイル（デフォルトはPDF）を検索し、コンテンツハッシュで追跡、メタデータをローカルのSQLiteデータベースに保存し、ドキュメントの内容を別のFTSデータベースにインデックスします。

## 特徴

- **設定可能なファイルスキャン** — `meta_config.json`を介して、任意のディレクトリやファイルタイプをスキャン対象に設定可能
- **カスタマイズ可能なメタデータ** — コードを触らずに独自のフィールド（テキスト、選択リスト、キーワードリスト）を定義可能
- **移動検知** — コンテンツハッシュでファイルを追跡するため、ファイル名の変更や移動を自動的に処理
- **紛失ファイルの追跡** — 削除されたファイルはフラグが立てられ、サイレントに削除されることはありません
- **メタデータ検索** — ファイル名、タイトル、キーワード、または任意のメタデータフィールドによる検索（LIKEベース）
- **全文検索** — SQLite FTS5を使用してドキュメント内のテキストを検索（CLIの`fts_search`コマンド、またはGUIのFull-textトグル）
- **自動メタデータ抽出** — 3レイヤーのパイプラインにより、PDFからタイトル、著者、発行年、キーワードを自動抽出（PDFメタデータ → ファイル名のヒューリスティック → 1ページ目のテキスト解析）
- **AI支援による抽出** — オプションでGoogle GeminiまたはOpenAI互換APIを統合し、より高品質なメタデータの提案が可能
- **ドラフト/確定のステージング** — 抽出された提案は「ドラフト」として保存され、確認後にカタログに反映。信頼度が高いフィールドは自動確定可能
- **GUIでのクリック可能なパス** — リストビューのパスセルをクリックすると、OSのデフォルトアプリでファイルを開けます
- **JSONエクスポート** — カタログ全体を他のツールで使用するためにエクスポート可能
- **インポート可能なAPI** — Jupyter NotebookやWebフレームワークから直接`ScribeFTS`クラスを利用可能

## 必要条件

- Python 3.14 以上
- Flask (`pip install flask`) — GUIモードのみ
- PyMuPDF (`pip install pymupdf`) — PDFのテキスト抽出およびメタデータ抽出用（欠落している場合は機能が段階的に制限されます）
- その他はPython標準ライブラリのみを使用

## クイックスタート

```bash
# リポジトリをクローン
git clone https://github.com/Gertrud-Violett/ScribeFTS.git
cd ScribeFTS

# オプションの依存関係をインストール
pip install flask pymupdf

# CLIまたはGUIモードで実行
python __main__.py --cli    # インタラクティブCLI
python __main__.py --gui    # ブラウザベースのGUI (localhost:5000)
```

初回実行時に、ScribeFTSは `data/library.db`、`data/fts.db`、`data/meta_config.json`、`data/ai_config.json` をデフォルト設定で作成し、ディレクトリのスキャンとインデックスを開始します。

## セットアップ手順

### 1. スキャンディレクトリの設定

`data/meta_config.json` を編集し、スキャンしたいフォルダを `scan_directories` フィールドに設定します。

### 2. メタデータフィールドの設定

`meta_config.json` の `fields` リストでメタデータカラムを定義します。各フィールドには `name`、`type` (`text`, `choice`, `list`)、オプションで `required` や `default` を設定できます。

### 3. AI支援抽出の設定 (任意)

AIによる高度な抽出を使用するには、`data/ai_config.json` を編集するか、GUIの **AI Config** ページを使用します。

## 自動メタデータ抽出

ScribeFTSは、情報が不足しているエントリに対してタイトル、著者、年、キーワードを自動提案します。抽出は以下の**3レイヤー・ウォーターフォール**で実行されます：

1. **レイヤー 1 — PDF内部メタデータ**: PDFファイルから直接情報を読み取ります。
2. **レイヤー 2 — ファイル名のヒューリスティック**: ファイル名やパスから年、著者名、キーワードを抽出します。
3. **レイヤー 3a — 1ページ目のテキスト解析 (AI無効)**: 正規表現を使用してタイトルや著者を検索します。
   **レイヤー 3b — AI抽出 (AI有効)**: 1ページ目のテキストをAIプロバイダーに送信し、情報を解析します。

提案は**ドラフト**として保存されます。`auto_commit_threshold` 以上の信頼度を持つフィールドは自動的にカタログに反映されます。

## CLI コマンド

| コマンド | 説明 |
|---|---|
| `refresh` | ディレクトリをスキャンし、新規・移動・紛失ファイルを更新。FTSインデックスを作成 |
| `list` | カタログ内の全ファイルを表示 |
| `search <query>` | メタデータフィールドを検索 |
| `fts_search <query>` | ドキュメント本文を全文検索 |
| `reindex` | FTSインデックスをゼロから再構築 |
| `show <hash_prefix>` | エントリの詳細を表示 |
| `update <hash_prefix> <field> <value>` | メタデータフィールドを更新 |
| `edit <hash_prefix>` | メタデータをインタラクティブに編集 |
| `suggest <hash_prefix>` | 特定のエントリに対して抽出パイプラインを実行 |
| `suggest_all` | 未入力のエントリすべてに対して抽出を実行 |
| `commit <hash_prefix>` | ドラフトをカタログに反映 |
| `delete <hash_prefix>` | データベースからエントリを削除（実ファイルは削除されません） |
| `export [path]` | JSON形式でエクスポート |
| `stats` | 統計情報を表示 |

## 全文検索

`fts_search` はドキュメントから抽出されたテキストを検索します。SQLite FTS5を使用しており、以下の機能をサポートしています：

- 単純なキーワード: `fts_search 振動`
- フレーズ検索: `fts_search "動荷重"`
- 論理演算: `fts_search 軸受 AND 疲労`
- カラムフィルタ: `fts_search body:振動`

## プロジェクト構造

```
ScribeFTS/
├── bin/ScribeFTS.py           # CLIエントリポイント
├── data/                      # データベースと設定 (自動生成)
├── lib/                       # コアライブラリモジュール
├── gui/                       # Flaskアプリとテンプレート
├── tests/                     # テストとサンプルドキュメント
└── docs/ARCHITECTURE.md       # 詳細なアーキテクチャドキュメント
```

## ライセンス

このプロジェクトは BSD 2-Clause License の下でライセンスされています。詳細は LICENSE を参照してください。
