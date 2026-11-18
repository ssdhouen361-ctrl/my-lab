import asyncio
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

import discord
from dotenv import dotenv_values, load_dotenv

BASE_DIR = Path(__file__).resolve().parent
REPO_DIR = Path(os.getenv("REPO_DIR", str(BASE_DIR.parent.parent))).resolve()
CONVERSATIONS_FILE = BASE_DIR / ".conversations.json"
ATTACHMENTS_DIR = BASE_DIR / "attachments"

# 1. 本プロジェクトの .env を読み込む
load_dotenv(BASE_DIR / ".env")

# 2. DISCORD_BOT_TOKEN が未設定なら music-automation/.env からトークンのみ共有利用する
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not TOKEN:
    fallback_env = REPO_DIR / "projects" / "music-automation" / ".env"
    if fallback_env.exists():
        TOKEN = dotenv_values(fallback_env).get("DISCORD_BOT_TOKEN")

TARGET_CHANNEL = os.getenv("DISCORD_CHANNEL_NAME", "gemini-agent")
AGY_BIN = os.getenv("AGY_BIN", "/Users/sasadayuto/.local/bin/agy")
AGY_MODE = os.getenv("AGY_MODE", "accept-edits")
AGY_TIMEOUT_SECONDS = int(os.getenv("AGY_TIMEOUT_SECONDS", "300"))
AUTO_GIT_PUSH = os.getenv("AUTO_GIT_PUSH", "true").lower() == "true"

_raw_allowed_ids = os.getenv("DISCORD_ALLOWED_USER_IDS", "").strip()
ALLOWED_USER_IDS: set[int] = {
    int(uid.strip()) for uid in _raw_allowed_ids.split(",") if uid.strip().isdigit()
}

# Discordメッセージの文字数上限(2000文字)に対する安全マージン
MAX_DISCORD_LENGTH = 1900

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
_agent_lock: Optional[asyncio.Lock] = None


def get_agent_lock() -> asyncio.Lock:
    """実行中のイベントループに紐づく asyncio.Lock を返す（Python 3.9互換）"""
    global _agent_lock
    if _agent_lock is None:
        _agent_lock = asyncio.Lock()
    return _agent_lock


def load_conversations() -> dict[str, str]:
    """チャンネル/スレッドIDごとの会話ID(conversation_id)を読み込む"""
    if not CONVERSATIONS_FILE.exists():
        return {}
    try:
        data = json.loads(CONVERSATIONS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_conversations(data: dict[str, str]) -> None:
    """チャンネル/スレッドIDごとの会話IDを保存する"""
    CONVERSATIONS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def is_target_channel(channel: discord.abc.Messageable) -> bool:
    """監視対象チャンネル(#gemini-agent)またはその配下のスレッドかを判定する"""
    if isinstance(channel, discord.Thread):
        parent = channel.parent
        return parent is not None and getattr(parent, "name", None) == TARGET_CHANNEL
    return getattr(channel, "name", None) == TARGET_CHANNEL


def is_authorized_user(message: discord.Message) -> bool:
    """
    実行を許可するユーザーかを判定する。
    DISCORD_ALLOWED_USER_IDS が未設定の場合は、サーバー所有者(Owner)のみ許可する。
    """
    if message.guild is None:
        return False
    if ALLOWED_USER_IDS:
        return message.author.id in ALLOWED_USER_IDS
    return message.author.id == message.guild.owner_id


def run_git(args: list[str]) -> tuple[int, str, str]:
    """my-lab リポジトリ内で git コマンドを同期実行する"""
    res = subprocess.run(
        ["git", *args],
        cwd=str(REPO_DIR),
        capture_output=True,
        text=True,
    )
    return res.returncode, res.stdout.strip(), res.stderr.strip()


def sync_git_before() -> Optional[str]:
    """作業ツリーがクリーンな場合のみ origin/main から最新を取得する"""
    code, status_out, _ = run_git(["status", "--porcelain"])
    if code == 0 and not status_out:
        pull_code, _, pull_err = run_git(["pull", "--rebase", "origin", "main"])
        if pull_code != 0:
            return f"事前 git pull 警告: {pull_err}"
    return None


def commit_and_push_changes(instruction_summary: str) -> tuple[bool, str, list[str]]:
    """
    作業ツリーに変更があれば自動でコミット＆プッシュする。
    戻り値: (プッシュを実行したか, ステータスメッセージ, 変更ファイル一覧)
    """
    code, status_out, err_out = run_git(["status", "--porcelain"])
    if code != 0:
        return False, f"git status 失敗: {err_out}", []

    if not status_out:
        return False, "ファイルの変更はありませんでした。", []

    changed_files = [line[3:].strip() for line in status_out.splitlines() if line.strip()]

    add_code, _, add_err = run_git(["add", "-A"])
    if add_code != 0:
        return False, f"git add 失敗: {add_err}", changed_files

    short_prompt = instruction_summary.replace("\n", " ")[:40]
    commit_msg = f"chore(discord-agent): {short_prompt}"
    commit_code, _, commit_err = run_git(["commit", "-m", commit_msg])
    if commit_code != 0:
        return False, f"git commit 失敗: {commit_err}", changed_files

    push_code, _, push_err = run_git(["push", "origin", "main"])
    if push_code != 0:
        return False, f"git push 失敗（ローカルにはコミット済み）: {push_err}", changed_files

    return True, "GitHub (`origin/main`) へ自動反映しました。", changed_files


def extract_json_result(stdout_text: str) -> Optional[dict]:
    """agy の標準出力から JSON 結果行を抽出する"""
    for line in reversed(stdout_text.splitlines()):
        line = line.strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict) and ("response" in parsed or "status" in parsed):
                return parsed
        except json.JSONDecodeError:
            continue
    return None


async def run_agy_prompt(prompt: str, conversation_id: Optional[str]) -> tuple[bool, str, Optional[str]]:
    """
    Antigravity CLI (agy) を非同期サブプロセスとして実行する。
    戻り値: (成功フラグ, AIからの返答またはエラー内容, 新しいconversation_id)
    """
    if not os.path.exists(AGY_BIN):
        return False, f"`{AGY_BIN}` が見つかりません。", conversation_id

    wrapped_prompt = (
        "あなたは my-lab リポジトリの専属エンジニアです。"
        "リポジトリ内の AGENTS.md のルールに従い、簡潔でわかりやすい日本語で回答してください。"
        "ファイルの作成・編集が必要な場合は my-lab 配下に対して直接実行してください"
        "（git commit / git push は呼び出し元のボットが自動で行うため、あなたが実行する必要はありません）。\n\n"
        f"【ユーザーからの指示】\n{prompt}"
    )

    cmd = [
        AGY_BIN,
        "-p",
        wrapped_prompt,
        "--output-format",
        "json",
        "--mode",
        AGY_MODE,
        "--sandbox",
        "--dangerously-skip-permissions",
        "--print-timeout",
        f"{AGY_TIMEOUT_SECONDS}s",
    ]
    if conversation_id:
        cmd.extend(["--conversation", conversation_id])

    env = os.environ.copy()
    env["PATH"] = f"{Path(AGY_BIN).parent}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(REPO_DIR),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=AGY_TIMEOUT_SECONDS + 30,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return False, f"タイムアウト（{AGY_TIMEOUT_SECONDS}秒）により処理を中断しました。", conversation_id

    stdout_text = stdout_bytes.decode("utf-8", errors="replace").strip()
    stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()

    parsed = extract_json_result(stdout_text)
    if proc.returncode != 0:
        detail = stderr_text or stdout_text or f"終了コード: {proc.returncode}"
        return False, f"agy 実行エラー:\n```\n{detail[:1500]}\n```", conversation_id

    if parsed:
        new_conv_id = parsed.get("conversation_id") or conversation_id
        status = parsed.get("status", "")
        response_text = (parsed.get("response") or "").strip()
        denied = parsed.get("denied_actions") or []
        if status and status != "SUCCESS":
            return False, f"agy ステータス異常 ({status}): {response_text or stderr_text}", new_conv_id
        if not response_text:
            detail = stderr_text or (f"拒否された操作: {denied}" if denied else "詳細不明")
            return False, f"応答テキストが空でした。\n```\n{detail[:1000]}\n```", new_conv_id
        return True, response_text, new_conv_id

    # JSON解析できない場合のフォールバック
    if stdout_text:
        return True, stdout_text, conversation_id
    return False, f"応答の解析に失敗しました。\n{stderr_text[:1000]}", conversation_id


def split_message(text: str, limit: int = MAX_DISCORD_LENGTH) -> list[str]:
    """2000文字を超える長文を行単位で分割する"""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current_lines: list[str] = []
    current_len = 0

    for line in text.splitlines(keepends=True):
        if len(line) > limit:
            if current_lines:
                chunks.append("".join(current_lines).rstrip())
                current_lines = []
                current_len = 0
            for i in range(0, len(line), limit):
                chunks.append(line[i : i + limit])
            continue

        if current_len + len(line) > limit:
            chunks.append("".join(current_lines).rstrip())
            current_lines = [line]
            current_len = len(line)
        else:
            current_lines.append(line)
            current_len += len(line)

    if current_lines:
        chunks.append("".join(current_lines).rstrip())

    return [c for c in chunks if c]


async def send_long_reply(message: discord.Message, text: str) -> None:
    """最初のメッセージは返信(reply)、続きは同じチャンネルに連投する"""
    chunks = split_message(text)
    if not chunks:
        return
    await message.reply(chunks[0], mention_author=False)
    for chunk in chunks[1:]:
        await message.channel.send(chunk)


def estimate_duration_label(prompt: str) -> str:
    """依頼内容の長さやキーワードから予測所要時間の目安を返す"""
    heavy_keywords = (
        "作成", "作って", "実装", "構築", "テスト", "修正", "設計",
        "リポジトリ", "ウィジェット", "アプリ", "スクリプト", "変更",
    )
    has_heavy_kw = any(kw in prompt for kw in heavy_keywords)
    if len(prompt) > 250 or (has_heavy_kw and len(prompt) > 100):
        return "約1〜3分"
    if has_heavy_kw or len(prompt) > 80:
        return "約30秒〜2分"
    return "約10〜30秒"


async def update_progress_loop(
    status_msg: discord.Message,
    estimate_label: str,
    started_at: float,
    stop_event: asyncio.Event,
) -> None:
    """処理中に15秒ごとに経過時間を受付メッセージへ上書き表示する"""
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=15)
            break
        except asyncio.TimeoutError:
            elapsed = int(time.monotonic() - started_at)
            try:
                await status_msg.edit(
                    content=f"⏳ Mac mini の `agy` が作業中です...（経過: **{elapsed}秒** / 目安: {estimate_label}）"
                )
            except Exception:
                pass


@client.event
async def on_ready():
    print("==========================================")
    print(f"✅ Discord AIエージェント起動: {client.user}")
    print(f"👀 監視チャンネル: #{TARGET_CHANNEL}（およびそのスレッド）")
    print(f"📁 作業リポジトリ: {REPO_DIR}")
    print(f"🤖 実行コマンド: {AGY_BIN} (mode={AGY_MODE}, sandbox=True)")
    print(f"🔄 GitHub自動プッシュ: {'ON' if AUTO_GIT_PUSH else 'OFF'}")
    print("==========================================")


@client.event
async def on_message(message: discord.Message):
    if message.author.bot or message.webhook_id is not None:
        return

    if not is_target_channel(message.channel):
        return

    if not is_authorized_user(message):
        print(f"⛔ 未許可ユーザーからのメッセージを無視: {message.author} (ID: {message.author.id})")
        return

    raw_text = message.content.strip()
    if not raw_text and not message.attachments:
        return

    lower_text = raw_text.lower()
    channel_key = str(message.channel.id)

    # 組み込みコマンド: !help
    if lower_text in ("!help", "ヘルプ"):
        await message.reply(
            "📖 **Discord AIエージェント 使い方**\n"
            f"- `#{TARGET_CHANNEL}`（またはこの中のスレッド）にそのまま日本語で指示を書くだけで、`agy` が Mac mini 上で作業して返信します。\n"
            "- 画像やファイルを添付して送ると、自動で Mac mini 内に保存して `agy` が読み取ります。\n"
            "- ファイルを作成・編集した場合は自動で GitHub (`origin/main`) にコミット＆プッシュします。\n"
            "- `!new` または `リセット` : 会話の記憶をリセットして新しい話題を始めます。\n"
            "- `!status` : `agy` とリポジトリの状態を確認します。\n"
            "- `!restart` または `再起動` : Bot自身を再起動して最新コードを反映します。\n"
            "- **スレッド機能** を使うと、話題ごとに別々の会話履歴を保てます！",
            mention_author=False,
        )
        return

    # 組み込みコマンド: !restart / 再起動
    if lower_text in ("!restart", "再起動"):
        await message.reply("🔄 Botを再起動します（数秒で復帰します）...", mention_author=False)
        os._exit(0)

    # 組み込みコマンド: !new / リセット
    if lower_text in ("!new", "リセット", "/reset"):
        conversations = load_conversations()
        conversations.pop(channel_key, None)
        save_conversations(conversations)
        await message.reply("🧹 このチャンネル（スレッド）の会話履歴をリセットしました。次のメッセージから新しい会話として開始します。", mention_author=False)
        return

    # 組み込みコマンド: !status
    if lower_text == "!status":
        ver_res = subprocess.run([AGY_BIN, "--version"], capture_output=True, text=True)
        agy_ver = ver_res.stdout.strip() or ver_res.stderr.strip() or "不明"
        _, git_branch, _ = run_git(["status", "-sb"])
        await message.reply(
            f"🖥️ **稼働ステータス**\n"
            f"- `agy`: `{agy_ver}`\n"
            f"- Git状態:\n```\n{git_branch}\n```",
            mention_author=False,
        )
        return

    lock = get_agent_lock()
    if lock.locked():
        await message.reply("⏳ 前の作業を実行中です。完了後に順番に処理します...", mention_author=False)

    async with lock:
        estimate_label = estimate_duration_label(raw_text)
        started_at = time.monotonic()
        status_msg = await message.reply(
            f"🤖 受け付けました！Mac mini の `agy` が作業を開始します（目安: **{estimate_label}**）",
            mention_author=False,
        )

        stop_event = asyncio.Event()
        progress_task = asyncio.create_task(
            update_progress_loop(status_msg, estimate_label, started_at, stop_event)
        )

        try:
            async with message.channel.typing():
                conversations = load_conversations()
                conv_id = conversations.get(channel_key)

                pull_warn = await asyncio.to_thread(sync_git_before)
                if pull_warn:
                    print(f"⚠️ {pull_warn}")

                # 添付ファイルがあればローカルに保存してプロンプトにパスを追記する
                saved_attachments: list[Path] = []
                if message.attachments:
                    ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
                    for idx, att in enumerate(message.attachments):
                        safe_name = f"{message.id}_{idx}_{Path(att.filename).name}"
                        dest_path = ATTACHMENTS_DIR / safe_name
                        try:
                            await att.save(dest_path)
                            saved_attachments.append(dest_path)
                        except Exception as e:
                            print(f"⚠️ 添付ファイル保存失敗 ({att.filename}): {e}")

                prompt_for_agy = raw_text or "添付されたファイルを確認してください。"
                if saved_attachments:
                    att_lines = "\n".join(f"- {p}" for p in saved_attachments)
                    prompt_for_agy += (
                        "\n\n【添付ファイル（read_file ツール等で直接読み取ってください）】\n"
                        f"{att_lines}"
                    )

                ok, reply_text, new_conv_id = await run_agy_prompt(prompt_for_agy, conv_id)

                if new_conv_id:
                    conversations[channel_key] = new_conv_id
                    save_conversations(conversations)

                footer = ""
                changed_files: list[str] = []
                if ok and AUTO_GIT_PUSH:
                    pushed, git_msg, changed_files = await asyncio.to_thread(
                        commit_and_push_changes, raw_text or "attachment"
                    )
                    if changed_files:
                        files_preview = ", ".join(f"`{f}`" for f in changed_files[:8])
                        if len(changed_files) > 8:
                            files_preview += f" ほか{len(changed_files) - 8}件"
                        icon = "📦" if pushed else "⚠️"
                        footer = f"\n\n---\n{icon} {git_msg}\n変更ファイル: {files_preview}"
        finally:
            stop_event.set()
            await progress_task

        elapsed_total = int(time.monotonic() - started_at)
        try:
            done_icon = "✅" if ok else "⚠️"
            await status_msg.edit(content=f"{done_icon} 処理完了（所要時間: **{elapsed_total}秒**）")
        except Exception:
            pass

        prefix = "" if ok else "⚠️ **エラーが発生しました**\n"
        await send_long_reply(message, f"{prefix}{reply_text}{footer}")

        # bot.py 自身が更新された場合は launchd に自動再起動させる
        if any("discord-ai-agent/bot.py" in f for f in changed_files):
            print("🔄 bot.py の更新を検知したため、プロセスを再起動します...")
            os._exit(0)


if __name__ == "__main__":
    if not TOKEN or TOKEN == "ここにトークンを貼り付け":
        print("❌ エラー: DISCORD_BOT_TOKEN が見つかりません。.env を確認してください。")
    else:
        client.run(TOKEN)
