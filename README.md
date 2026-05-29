# job-match-cli

求人テキストを読み込み、自分の保有スキル・ツールと照合して **マッチ度** を算出し、**応募履歴** を記録する、転職活動のための個人用CLIツールです。

「この求人、必須要件のどれをカバーできていて、何が足りないのか？」を一目で把握し、応募の記録までローカルで完結させることを目的にしています。外部API・データベース・GUIは一切使わず、すべてローカルファイルで動きます。

## 特長

- 📄 **求人 × プロフィールの自動照合** — 求人テキストの「必須要件 / 歓迎要件」を見出しから自動で読み分け、カバー率を `必須 X/Y、歓迎 X/Y` の形式で表示
- ⚠️ **不足キーワードの警告** — 求人に出てくるが自分の `profile.yaml` に無いキーワードを抽出して提示
- 🗂 **応募履歴の管理** — 応募先・ポジション・カバー率・応募日を CSV に追記し、整形テーブルで一覧表示
- 🧩 **依存は最小限** — 標準ライブラリ + PyYAML のみ

## 動作環境

- Python 3.8 以上
- 依存ライブラリ: PyYAML

## インストール

```bash
git clone <このリポジトリのURL>
cd job-match-cli

# 仮想環境（任意）
python3 -m venv .venv
source .venv/bin/activate

# 依存のインストール
pip install -r requirements.txt
```

## プロフィールの設定

自分の保有スキル・ツールを [profile.yaml](profile.yaml) に書きます。ここに書いた項目が照合の基準になります。

```yaml
skills:
  - Python
  - Django
  - React
  - SQL

tools:
  - Git
  - Docker
  - AWS
  - PostgreSQL
```

`JavaScript` / `JS`、`Go` / `golang` のような表記ゆれは内蔵辞書が吸収するため、正式名で書けばOKです。辞書に無い独自スキルを書いても、そのまま照合対象に加わります。

## 使い方

3つのサブコマンドがあります。

### 1. `match` — 求人と照合する

求人テキスト（`.md` / `.txt`）を渡すと、`profile.yaml` と照合してマッチ度を表示します。

```bash
python job_match.py match <求人ファイル> [--profile profile.yaml]
```

**実行例:**

```bash
$ python job_match.py match examples/sample_job.md
📄 求人ファイル : examples/sample_job.md
👤 プロフィール : profile.yaml（スキル 8 / ツール 6）

──────── マッチ度 ────────
  必須要件 : 5/6 (83%)
  歓迎要件 : 4/8 (50%)

✔ 保有スキルでカバー:
    AWS、Django、Docker、Git、PostgreSQL、Python、REST API、React、TypeScript
⚠ 不足キーワード（必須）: FastAPI
⚠ 不足キーワード（歓迎）: CI/CD、GCP、GraphQL、Kubernetes

💡 この応募を記録するには:
    python job_match.py add --company "社名" --position "ポジション名" --coverage "必須83% 歓迎50%"
```

> 求人テキストは `必須要件` / `歓迎要件`（`required` / `preferred` 等の英語見出しも可）といった見出し行でセクションを判定します。見出しが見つからない場合は全文を必須要件として照合します。

### 2. `add` — 応募履歴を記録する

応募先・ポジション・カバー率を [applications.csv](applications.csv) に1行追記します。`--date` を省略すると今日の日付になります。CSVが無ければ自動で作成します。

```bash
python job_match.py add \
  --company "サンプル株式会社" \
  --position "バックエンドエンジニア" \
  --coverage "必須83% 歓迎50%" \
  [--date 2026-05-29]
```

**実行例:**

```bash
$ python job_match.py add --company "サンプル株式会社" --position "バックエンドエンジニア" --coverage "必須83% 歓迎50%"
✅ 応募を記録しました → applications.csv
    2026-05-29 / サンプル株式会社 / バックエンドエンジニア / 必須83% 歓迎50%
```

### 3. `list` — 応募履歴を一覧表示する

記録済みの応募を整形テーブルで表示します。

```bash
python job_match.py list
```

**実行例:**

```bash
$ python job_match.py list
+------------+------------------+------------------------+-----------------+
| 応募日     | 応募先           | ポジション             | カバー率        |
+------------+------------------+------------------------+-----------------+
| 2026-05-29 | サンプル株式会社 | バックエンドエンジニア | 必須83% 歓迎50% |
+------------+------------------+------------------------+-----------------+

合計 1 件
```

## ファイル構成

```
job-match-cli/
├── job_match.py        # メインCLIスクリプト（match / add / list）
├── profile.yaml        # 保有スキル・ツールの定義
├── requirements.txt    # 依存（PyYAML）
├── README.md
├── .gitignore
└── examples/
    └── sample_job.md   # 動作確認用のサンプル求人
```

`applications.csv` は `add` 実行時に自動生成されます。個人情報を含むため `.gitignore` で除外しています。

## 仕組み（概要）

1. `profile.yaml` のスキル・ツールを、内蔵キーワード辞書（言語・フレームワーク・クラウド・ツール等）にマージして「照合用の語彙」を作ります。
2. 求人テキストを行単位で走査し、見出しから必須／歓迎セクションに分割します。
3. 各セクションに出現する語彙キーワードを抽出し、保有スキルとの積集合からカバー率を計算。差集合を「不足キーワード」として提示します。
4. キーワード照合は英数字の途中一致を防ぐ境界判定を行い、`C++` や `.NET` のような記号付きキーワードも扱えます。

## ライセンス

MIT License

---

このツールは **Claude Code で設計・実装** しました。
