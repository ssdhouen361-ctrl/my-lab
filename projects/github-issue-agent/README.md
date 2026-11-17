# スマホ連動 GitHub Issue AIエージェント (Gemini CLI GitHub Actions)

スマートフォン（Galaxy S26 Ultra）やタブレット（Galaxy Tab）のブラウザ／GitHubアプリから、GitHubの **Issues（イシュー：課題・メモ欄）** に `@gemini-cli` とメンションして書き込むだけで、クラウド上でGeminiが自動的に起動し、リポジトリの調査・ファイル作成・編集・返信を自律的に行う仕組みです。

Mac miniの電源が入っていない外出先からでも、スマホだけでアイデアの記録やコード生成・ドキュメント整理をAIに指示できます。

---

## 1. システム全体像（アーキテクチャ）

```text
[Galaxy S26 Ultra / Galaxy Tab]
  │ ① GitHubのIssue作成、またはコメントで「@gemini-cli 〜して」と投稿
  ▼
[GitHub Actions (クラウド上の仮想サーバー)]
  │ ② 「@gemini-cli」という文字を検知して自動起動 (.github/workflows/gemini-cli.yml)
  ▼
[Gemini CLI (google-github-actions/run-gemini-cli)]
  │ ③ AGENTS.md のルールを読み込み、指示された作業（ファイル作成・調査など）を実行
  ▼
[GitHub リポジトリ (my-lab)]
  │ ④ 作業結果をファイルとしてコミット＆プッシュ、またはIssueのコメント欄に返信！
```

### 登場する用語の補足
- **GitHub Issues（イシュー）**: リポジトリ内に作れる「掲示板・ToDoリスト」のような機能です。今回はここを「AIへのチャット指示窓口」として使います。
- **GitHub Actions（ギットハブ・アクションズ）**: GitHubが提供するクラウド上の自動実行システムです。「Issueが書かれたらプログラムを動かす」といった自動化を、自宅のMacを使わずにGitHubのサーバー上で無料枠内で実行できます。
- **GitHub Secrets（シークレッツ）**: APIキーなどの「秘密のパスワード」をGitHub上に安全に保管する金庫のような機能です。コードに直接書かずに済むため、外部に漏洩しません。

---

## 2. 関連ファイル構成

```text
my-lab/
├── .github/
│   └── workflows/
│       └── gemini-cli.yml             # GitHub Actionsの自動起動設定ファイル（本体）
├── projects/
│   └── github-issue-agent/
│       └── README.md                  # 本設計書・セットアップ手順書
└── AGENTS.md                          # AIへの共通ルール（Gemini CLIもこれを参照します）
```

---

## 3. セキュリティと安全設計

1. **実行ユーザーの制限（タダ乗り防止）**  
   ワークフロー（`gemini-cli.yml`）には、**リポジトリの所有者（OWNER / MEMBER / COLLABORATOR）からの書き込みのみに反応する**フィルターを設定しています。万が一リポジトリが公開（Public）状態でも、第三者が勝手に `@gemini-cli` と書き込んでAPI枠を消費することはできません。
2. **秘密情報の保護**  
   GoogleのAIを動かすための `GEMINI_API_KEY` は、GitHub Secretsに格納して呼び出す設計としています。

---

## 4. 初回セットアップ手順（Web画面での設定）

ワークフローファイルをGitHubに反映（プッシュ）した後、以下の2つの設定を行うだけで使えるようになります。

### Step 1: Google AI Studio で APIキーを発行する
1. ブラウザで **[Google AI Studio (API Keys)](https://aistudio.google.com/app/apikey)** にアクセスし、Googleアカウントでログインします。
2. **「Create API key」**（APIキーを作成）ボタンをクリックします。
3. 生成された長い文字列（`AIza...` から始まるキー）をコピーして控えておきます。

### Step 2: GitHub リポジトリの Secrets に登録する
1. GitHubの自分のリポジトリ（`my-lab`）のページを開きます。
2. 上部メニューの **「Settings」**（⚙️設定）タブをクリックします。
3. 左側のサイドバーを下にスクロールし、**「Secrets and variables」** ＞ **「Actions」** をクリックします。
4. 緑色の **「New repository secret」** ボタンをクリックします。
5. 以下の通りに入力します：
   - **Name（名前）**: `GEMINI_API_KEY` （※大文字・アンダースコアまで一字一句同じにします）
   - **Secret（値）**: Step 1でコピーしたAPIキーを貼り付けます。
6. **「Add secret」** を押して保存すれば準備完了です！

---

## 5. 使い方（スマホからの指示出し）

1. Galaxyのブラウザまたは **GitHubモバイルアプリ** で `my-lab` リポジトリを開きます。
2. **「Issues」** タブを開き、**「New issue」**（新しいIssueを作成）を押します。
3. タイトル（例：`アイデアメモの整理`）と、本文に **`@gemini-cli`** を含めて指示を書きます。

### 指示の例（コピペして使えます）

**例1：質問・リポジトリの確認**
```text
@gemini-cli
現在のリポジトリの構成と、進行中のプロジェクトを分かりやすく要約して教えてください。
```

**例2：スマホからアイデアメモやファイルを作成させる**
```text
@gemini-cli
新しいアイデアを思いついたので、`docs/ideas.md` というファイルを作成して、以下の内容をMarkdownで綺麗にまとめてコミット・プッシュしてください。
完了したらこのIssueに返信してください。

・寝る前に「おやすみ」とスマホでボタンを押したら、Macの画面をスリープさせて音楽をフェードアウトする仕組みを作りたい
```

4. 投稿すると、数秒後にGeminiから **「🤖 リクエストを受け付けました！」** という一次返信がつき、1〜2分ほどで作業完了の報告コメントが届きます（進行状況は **「Actions」** タブからもリアルタイムで見られます）。
