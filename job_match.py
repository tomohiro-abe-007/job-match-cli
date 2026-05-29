#!/usr/bin/env python3
"""job-match-cli — 求人テキストと自分の保有スキルを照合する個人用CLIツール。

サブコマンド:
    match   求人テキストを読み込み、profile.yaml と照合してマッチ度を表示する
    add     応募履歴を applications.csv に1行追記する
    list    applications.csv の内容を表形式で一覧表示する

外部API・DB・GUIは使わず、すべてローカルファイルで完結する。
依存は標準ライブラリ + PyYAML のみ。
"""
from __future__ import annotations

import argparse
import csv
import datetime
import re
import sys
import unicodedata
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover - 依存未インストール時の親切なメッセージ
    sys.exit("PyYAML が見つかりません。`pip install -r requirements.txt` を実行してください。")


# --------------------------------------------------------------------------- #
# 設定
# --------------------------------------------------------------------------- #

DEFAULT_PROFILE = Path("profile.yaml")
DEFAULT_CSV = Path("applications.csv")
CSV_HEADER = ["応募日", "応募先", "ポジション", "カバー率"]

# 求人テキストの見出し判定に使うマーカー（小文字で比較する）
MUST_MARKERS = ("必須", "必要", "required", "must have", "must-have", "requirements", "qualifications")
NICE_MARKERS = ("歓迎", "尚可", "あれば", "ベター", "preferred", "nice to have", "nice-to-have", "bonus")

# 内蔵キーワード辞書: 正規名 -> 別名リスト（別名は小文字で記述）
# profile.yaml に書いたスキル・ツールもここに自動マージされるため、
# 辞書に無い独自スキルも認識・照合できる。
KNOWN_KEYWORDS: Dict[str, List[str]] = {
    # --- プログラミング言語 ---
    "Python": ["python3"],
    "JavaScript": ["js"],
    "TypeScript": ["ts"],
    "Java": [],
    "Kotlin": [],
    "Swift": [],
    "Go": ["golang"],
    "Ruby": [],
    "PHP": [],
    "Rust": [],
    "Scala": [],
    "C++": ["cpp"],
    "C#": ["csharp"],
    "SQL": [],
    # --- フレームワーク / ライブラリ ---
    "Django": [],
    "Flask": [],
    "FastAPI": [],
    "Rails": ["ruby on rails"],
    "React": ["react.js", "reactjs"],
    "Vue": ["vue.js", "vuejs"],
    "Next.js": ["nextjs", "next"],
    "Node.js": ["nodejs", "node"],
    "Express": ["express.js"],
    "Spring": ["spring boot"],
    "Laravel": [],
    "TensorFlow": [],
    "PyTorch": [],
    "pandas": [],
    "NumPy": ["numpy"],
    # --- クラウド / インフラ ---
    "AWS": ["amazon web services"],
    "GCP": ["google cloud", "google cloud platform"],
    "Azure": [],
    "Docker": [],
    "Kubernetes": ["k8s"],
    "Terraform": [],
    "Ansible": [],
    "CI/CD": ["ci / cd"],
    "GitHub Actions": [],
    "Linux": [],
    "nginx": [],
    # --- データベース ---
    "PostgreSQL": ["postgres"],
    "MySQL": [],
    "SQLite": [],
    "MongoDB": ["mongo"],
    "Redis": [],
    "Elasticsearch": [],
    "BigQuery": [],
    # --- ツール / その他 ---
    "Git": [],
    "GitHub": [],
    "GitLab": [],
    "Jira": [],
    "Figma": [],
    "Slack": [],
    "REST API": ["rest", "restful"],
    "GraphQL": [],
    "gRPC": [],
    "Kafka": [],
    "Agile": ["アジャイル"],
    "Scrum": ["スクラム"],
    "Microservices": ["microservice", "マイクロサービス"],
    "Machine Learning": ["機械学習", "ml"],
    "Data Analysis": ["データ分析"],
}


# --------------------------------------------------------------------------- #
# キーワード照合
# --------------------------------------------------------------------------- #

def build_vocabulary(profile_terms: Iterable[str]) -> Dict[str, Dict[str, object]]:
    """照合用の語彙辞書を組み立てる。

    返り値: ``{正規名(小文字): {"display": 表示名, "terms": {検索語(小文字)...}}}``
    内蔵辞書に profile のスキル・ツールをマージする。
    """
    vocab: Dict[str, Dict[str, object]] = {}
    for canonical, aliases in KNOWN_KEYWORDS.items():
        key = canonical.lower()
        vocab[key] = {"display": canonical, "terms": {key, *(a.lower() for a in aliases)}}

    for term in profile_terms:
        key = term.lower()
        if key in vocab:
            continue  # 既に内蔵辞書にある（正規名一致）
        # 別名として既存の正規名に一致するなら新規追加しない
        if any(key in entry["terms"] for entry in vocab.values()):  # type: ignore[operator]
            continue
        vocab[key] = {"display": term, "terms": {key}}
    return vocab


def _keyword_pattern(term: str) -> "re.Pattern[str]":
    """英数字の途中一致を防ぐ境界付きの正規表現を作る（C++ や .NET も扱える）。"""
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])")


def find_keywords(text: str, vocab: Dict[str, Dict[str, object]]) -> Set[str]:
    """``text`` 中に出現する語彙の正規名（小文字キー）の集合を返す。"""
    lowered = text.lower()
    found: Set[str] = set()
    for key, entry in vocab.items():
        for term in entry["terms"]:  # type: ignore[union-attr]
            if _keyword_pattern(term).search(lowered):
                found.add(key)
                break
    return found


def resolve_profile_terms(profile_terms: Iterable[str], vocab: Dict[str, Dict[str, object]]) -> Set[str]:
    """保有スキル・ツールを語彙の正規名キーへ正規化した集合を返す。"""
    resolved: Set[str] = set()
    for term in profile_terms:
        low = term.lower()
        match = next((k for k, e in vocab.items() if low in e["terms"]), low)  # type: ignore[operator]
        resolved.add(match)
    return resolved


# --------------------------------------------------------------------------- #
# 求人テキストの解析
# --------------------------------------------------------------------------- #

def _is_heading(line: str) -> bool:
    """見出しらしい行か（短い・記号付き・コロン終わり等）を判定する。"""
    stripped = line.strip().strip("#＃ 　").strip("【】[]").strip()
    if not stripped:
        return False
    if line.lstrip().startswith(("#", "＃")):
        return True
    if line.strip().startswith(("【", "[")):
        return True
    if stripped.endswith((":", "：")):
        return True
    return len(stripped) <= 30


def _classify(line: str) -> str:
    """見出し行を 'must' / 'nice' / '' に分類する。"""
    low = line.lower()
    if any(m in low for m in NICE_MARKERS):
        return "nice"
    if any(m in low for m in MUST_MARKERS):
        return "must"
    return ""


def split_sections(text: str) -> Dict[str, str]:
    """求人テキストを必須(must)・歓迎(nice)・その他(other)に分割する。

    行を上から走査し、見出しらしい行でセクションを切り替える単純な
    ヒューリスティック。見出しが一つも見つからない場合は全文を必須扱いにする。
    """
    sections: Dict[str, List[str]] = {"must": [], "nice": [], "other": []}
    current = "other"
    found_heading = False

    for line in text.splitlines():
        if _is_heading(line):
            label = _classify(line)
            if label:
                current = label
                found_heading = True
                continue  # 見出し行自体は本文に含めない
        sections[current].append(line)

    if not found_heading:
        # 見出しが無い求人は、全文を必須要件とみなして照合する
        return {"must": text, "nice": "", "other": ""}

    return {k: "\n".join(v) for k, v in sections.items()}


# --------------------------------------------------------------------------- #
# プロフィール読込
# --------------------------------------------------------------------------- #

def load_profile(path: Path) -> Tuple[List[str], int, int]:
    """profile.yaml を読み込み (保有スキル・ツールの一覧, 必須側件数, 歓迎側件数) を返す。

    新形式の ``required_skills`` / ``preferred_skills`` を読み込む。
    保有しているかどうかが照合の基準であり、必須側・歓迎側のどちらに
    出てくるかは求人テキスト側で判定するため、両者は結合して扱う。
    （旧形式の ``skills`` / ``tools`` も後方互換として受け付ける。）
    """
    if not path.exists():
        sys.exit(f"プロフィールが見つかりません: {path}\nprofile.yaml を用意してください。")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        sys.exit(f"profile.yaml の読み込みに失敗しました: {exc}")

    def clean(key: str) -> List[str]:
        return [str(v).strip() for v in (data.get(key) or []) if str(v).strip()]

    required = clean("required_skills") or clean("skills")
    preferred = clean("preferred_skills") or clean("tools")
    if not required and not preferred:
        sys.exit("profile.yaml に required_skills / preferred_skills が定義されていません。")
    return required + preferred, len(required), len(preferred)


# --------------------------------------------------------------------------- #
# 表示ユーティリティ（東アジア文字幅対応）
# --------------------------------------------------------------------------- #

def _display_width(text: str) -> int:
    """全角文字を2幅として文字列の表示幅を計算する。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * (width - _display_width(text))


def render_table(header: List[str], rows: List[List[str]]) -> str:
    """ヘッダーと行から整形済みのテキストテーブルを作る。"""
    widths = [_display_width(h) for h in header]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], _display_width(cell))

    def fmt(cells: List[str]) -> str:
        return "| " + " | ".join(_pad(c, widths[i]) for i, c in enumerate(cells)) + " |"

    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    lines = [sep, fmt(header), sep]
    lines += [fmt(row) for row in rows]
    lines.append(sep)
    return "\n".join(lines)


def _ratio(covered: int, total: int) -> str:
    if total == 0:
        return "0/0 (対象キーワードなし)"
    pct = round(covered / total * 100)
    return f"{covered}/{total} ({pct}%)"


# --------------------------------------------------------------------------- #
# サブコマンド: match
# --------------------------------------------------------------------------- #

def cmd_match(args: argparse.Namespace) -> int:
    job_path = Path(args.jobfile)
    if not job_path.exists():
        sys.exit(f"求人ファイルが見つかりません: {job_path}")
    if job_path.suffix.lower() not in (".md", ".txt"):
        print(f"⚠ 警告: 想定外の拡張子です（.md / .txt 推奨）: {job_path.suffix}", file=sys.stderr)

    job_text = job_path.read_text(encoding="utf-8")
    profile_terms, n_required, n_preferred = load_profile(Path(args.profile))

    vocab = build_vocabulary(profile_terms)
    profile_keys = resolve_profile_terms(profile_terms, vocab)
    sections = split_sections(job_text)

    must_kw = find_keywords(sections["must"], vocab)
    nice_kw = find_keywords(sections["nice"], vocab)

    covered_must = must_kw & profile_keys
    covered_nice = nice_kw & profile_keys
    missing_must = sorted(must_kw - profile_keys)
    missing_nice = sorted((nice_kw - profile_keys) - must_kw)

    def names(keys: Iterable[str]) -> List[str]:
        return sorted(str(vocab[k]["display"]) for k in keys)

    must_str = _ratio(len(covered_must), len(must_kw))
    nice_str = _ratio(len(covered_nice), len(nice_kw))
    must_pct = round(len(covered_must) / len(must_kw) * 100) if must_kw else 0
    nice_pct = round(len(covered_nice) / len(nice_kw) * 100) if nice_kw else 0

    print(f"📄 求人ファイル : {job_path}")
    print(f"👤 プロフィール : {args.profile}（必須側 {n_required} / 歓迎側 {n_preferred}）")
    print()
    print("──────── マッチ度 ────────")
    print(f"  必須要件 : {must_str}")
    print(f"  歓迎要件 : {nice_str}")
    print()

    if covered_must or covered_nice:
        print("✔ 保有スキルでカバー:")
        print("    " + "、".join(names(covered_must | covered_nice)))
    if missing_must:
        print(f"⚠ 不足キーワード（必須）: {'、'.join(names(missing_must))}")
    if missing_nice:
        print(f"⚠ 不足キーワード（歓迎）: {'、'.join(names(missing_nice))}")
    if not (missing_must or missing_nice):
        print("🎉 不足キーワードはありません。")

    coverage = f"必須{must_pct}% 歓迎{nice_pct}%"
    print()
    print("💡 この応募を記録するには:")
    print(
        f'    python job_match.py add --company "社名" '
        f'--position "ポジション名" --coverage "{coverage}"'
    )
    return 0


# --------------------------------------------------------------------------- #
# サブコマンド: add
# --------------------------------------------------------------------------- #

def cmd_add(args: argparse.Namespace) -> int:
    csv_path = Path(args.csv)
    date = args.date or datetime.date.today().isoformat()
    row = [date, args.company, args.position, args.coverage]

    is_new = not csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(CSV_HEADER)
        writer.writerow(row)

    print(f"✅ 応募を記録しました → {csv_path}")
    print(f"    {date} / {args.company} / {args.position} / {args.coverage}")
    return 0


# --------------------------------------------------------------------------- #
# サブコマンド: list
# --------------------------------------------------------------------------- #

def cmd_list(args: argparse.Namespace) -> int:
    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"応募履歴がまだありません（{csv_path} が存在しません）。")
        print("`add` サブコマンドで記録を追加してください。")
        return 0

    with csv_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    if len(rows) <= 1:
        print("応募履歴は空です。")
        return 0

    header, *data = rows
    print(render_table(header, data))
    print(f"\n合計 {len(data)} 件")
    return 0


# --------------------------------------------------------------------------- #
# argparse
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="job_match.py",
        description="求人テキストと保有スキルを照合し、応募履歴を記録するCLIツール。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # match
    p_match = sub.add_parser("match", help="求人テキストとプロフィールを照合する")
    p_match.add_argument("jobfile", help="求人テキストファイル（.md / .txt）")
    p_match.add_argument(
        "--profile", default=str(DEFAULT_PROFILE),
        help=f"プロフィールYAML（既定: {DEFAULT_PROFILE}）",
    )
    p_match.set_defaults(func=cmd_match)

    # add
    p_add = sub.add_parser("add", help="応募履歴をCSVに追記する")
    p_add.add_argument("--company", required=True, help="応募先（会社名）")
    p_add.add_argument("--position", required=True, help="ポジション名")
    p_add.add_argument("--coverage", required=True, help='カバー率（例: "必須80% 歓迎50%"）')
    p_add.add_argument("--date", help="応募日 YYYY-MM-DD（既定: 今日）")
    p_add.add_argument(
        "--csv", default=str(DEFAULT_CSV),
        help=f"応募履歴CSV（既定: {DEFAULT_CSV}）",
    )
    p_add.set_defaults(func=cmd_add)

    # list
    p_list = sub.add_parser("list", help="応募履歴を一覧表示する")
    p_list.add_argument(
        "--csv", default=str(DEFAULT_CSV),
        help=f"応募履歴CSV（既定: {DEFAULT_CSV}）",
    )
    p_list.set_defaults(func=cmd_list)

    return parser


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
