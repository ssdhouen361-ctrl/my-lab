import asyncio
from dataclasses import dataclass, field
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

import discord
from dotenv import dotenv_values, load_dotenv

BASE_DIR = Path(__file__).resolve().parent
REPO_DIR = Path(os.getenv("REPO_DIR", str(BASE_DIR.parent.parent))).resolve()
CONVERSATIONS_FILE = BASE_DIR / ".conversations.json"
BG_CONVERSATIONS_FILE = BASE_DIR / ".bg_conversations.json"
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
AGY_TIMEOUT_SECONDS = int(os.getenv("AGY_TIMEOUT_SECONDS", "900"))
AGY_BG_TIMEOUT_SECONDS = int(os.getenv("AGY_BG_TIMEOUT_SECONDS", "0"))  # 0 = 時間制限なし
AGY_MAX_BG_JOBS = int(os.getenv("AGY_MAX_BG_JOBS", "3"))
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
_git_lock: Optional[asyncio.Lock] = None
current_agy_proc: Optional[asyncio.subprocess.Process] = None
stop_requested: bool = False


@dataclass
class BgJob:
    job_id: int
    prompt_summary: str
    channel_name: str
    started_at: float
    status: str = "running"  # running / done / error / cancelled
    finished_at: Optional[float] = None
    conversation_id: Optional[str] = None
    proc: Optional[asyncio.subprocess.Process] = None
    task: Optional[asyncio.Task] = None
    cancel_requested: bool = False
    result_note: str = ""


bg_jobs: dict[int, BgJob] = {}
next_bg_job_id: int = 1


def get_agent_lock() -> asyncio.Lock:
    """実行中のイベントループに紐づく asyncio.Lock を返す（Python 3.9互換）"""
    global _agent_lock
    if _agent_lock is None:
        _agent_lock = asyncio.Lock()
    return _agent_lock


def get_git_lock() -> asyncio.Lock:
    """表チャットと裏エージェントの git 操作衝突を防ぐ Lock を返す"""
    global _git_lock
    if _git_lock is None:
        _git_lock = asyncio.Lock()
    return _git_lock


def load_bg_conversations() -> dict[str, str]:
    """裏エージェントID(文字列)ごとの conversation_id を読み込む"""
    if not BG_CONVERSATIONS_FILE.exists():
        return {}
    try:
        data = json.loads(BG_CONVERSATIONS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_bg_conversations(data: dict[str, str]) -> None:
    """裏エージェントIDごとの conversation_id を保存する"""
    BG_CONVERSATIONS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def init_next_bg_job_id() -> None:
    """再起動後もジョブ番号が重複しないよう保存済み最大ID+1から開始する"""
    global next_bg_job_id
    saved = load_bg_conversations()
    numeric_ids = [int(k) for k in saved.keys() if k.isdigit()]
    if numeric_ids:
        next_bg_job_id = max(numeric_ids) + 1


def format_elapsed(seconds: int) -> str:
    """経過秒数を読みやすい日本語表記にする"""
    if seconds < 60:
        return f"{seconds}秒"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}分{sec}秒"
    hours, rem_min = divmod(minutes, 60)
    return f"{hours}時間{rem_min}分"


def parse_bg_command(raw_text: str) -> Optional[tuple[Optional[int], str]]:
    """
    !bg / !裏 コマンドを解析する。
    一致しない場合は None。
    一致した場合は (継続するジョブ番号 or None, 指示本文) を返す。
    例:
      '!bg Web碁盤を設計して'     -> (None, 'Web碁盤を設計して')
      '!bg #2 続きをお願い'       -> (2, '続きをお願い')
      '!bg' (添付ファイルのみ)    -> (None, '')
    """
    normalized = raw_text.strip()
    if normalized.startswith("！"):
        normalized = "!" + normalized[1:]
    match = re.match(r"^!(?:bg|裏)(?:\s+(.*))?$", normalized, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    rest = (match.group(1) or "").strip()
    resume_match = re.match(r"^#(\d+)(?:\s+(.*))?$", rest, flags=re.DOTALL)
    if resume_match:
        return int(resume_match.group(1)), (resume_match.group(2) or "").strip()
    return None, rest


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


def commit_and_push_changes(
    instruction_summary: str, scope: str = "discord-agent"
) -> tuple[bool, str, list[str]]:
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
    commit_msg = f"chore({scope}): {short_prompt}"
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


async def run_agy_prompt(
    prompt: str,
    conversation_id: Optional[str],
    timeout_seconds: Optional[int] = None,
    bg_job: Optional[BgJob] = None,
) -> tuple[bool, str, Optional[str]]:
    """
    Antigravity CLI (agy) を非同期サブプロセスとして実行する。
    bg_job が指定された場合はバックグラウンド専属エージェントとして独立実行する。
    timeout_seconds=0 の場合は時間制限なし（完了まで待機）。
    戻り値: (成功フラグ, AIからの返答またはエラー内容, 新しいconversation_id)
    """
    if not os.path.exists(AGY_BIN):
        return False, f"`{AGY_BIN}` が見つかりません。", conversation_id

    effective_timeout = AGY_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds

    bg_note = ""
    if bg_job is not None:
        bg_note = (
            f"あなたはバックグラウンド専属エージェント（ジョブ #{bg_job.job_id}）として起動されました。"
            "時間に余裕があるため、必要に応じて調査・複数視点の検討（サブエージェント活用等）を丁寧に行い、"
            "わかりやすい成果物を my-lab 配下に残してください。\n"
        )

    wrapped_prompt = (
        "あなたは my-lab リポジトリの専属エンジニアです。"
        "リポジトリ内の AGENTS.md のルールに従い、簡潔でわかりやすい日本語で回答してください。"
        "ファイルの作成・編集が必要な場合は my-lab 配下に対して直接実行してください"
        "（git commit / git push は呼び出し元のボットが自動で行うため、あなたが実行する必要はありません）。\n"
        f"{bg_note}\n"
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
        f"{effective_timeout}s",
    ]
    if conversation_id:
        cmd.extend(["--conversation", conversation_id])

    env = os.environ.copy()
    env["PATH"] = f"{Path(AGY_BIN).parent}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

    global current_agy_proc, stop_requested
    if bg_job is None:
        stop_requested = False

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(REPO_DIR),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    if bg_job is not None:
        bg_job.proc = proc
    else:
        current_agy_proc = proc

    try:
        if effective_timeout > 0:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=effective_timeout + 30,
            )
        else:
            stdout_bytes, stderr_bytes = await proc.communicate()
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return False, f"タイムアウト（{effective_timeout}秒）により処理を中断しました。", conversation_id
    finally:
        if bg_job is not None:
            bg_job.proc = None
        else:
            current_agy_proc = None

    was_cancelled = bg_job.cancel_requested if bg_job is not None else stop_requested
    if was_cancelled:
        return False, "__STOPPED_BY_USER__", conversation_id

    stdout_text = stdout_bytes.decode("utf-8", errors="replace").strip()
    stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()

    parsed = extract_json_result(stdout_text)
    new_conv_id = (parsed.get("conversation_id") if parsed else None) or conversation_id
    if proc.returncode != 0:
        detail = stderr_text or stdout_text or f"終了コード: {proc.returncode}"
        if "print_timeout" in detail or "DEADLINE_EXCEEDED" in detail:
            partial_resp = ((parsed or {}).get("response") or "").strip()
            msg = (
                f"作業が {effective_timeout}秒 を超えたため一時中断しました。\n"
                "「続きをお願い」と送れば、同じ会話の途中から再開できます。"
            )
            if partial_resp:
                msg += f"\n\n【途中までの出力】\n{partial_resp[:1200]}"
            return False, msg, new_conv_id
        return False, f"agy 実行エラー:\n```\n{detail[:1500]}\n```", new_conv_id

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


async def save_attachments_and_build_prompt(message: discord.Message, raw_prompt: str) -> str:
    """添付ファイルがあればローカルに保存し、プロンプトにファイルパスを追記して返す"""
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

    prompt_for_agy = raw_prompt or "添付されたファイルを確認してください。"
    if saved_attachments:
        att_lines = "\n".join(f"- {p}" for p in saved_attachments)
        prompt_for_agy += (
            "\n\n【添付ファイル（read_file ツール等で直接読み取ってください）】\n"
            f"{att_lines}"
        )
    return prompt_for_agy


def get_running_bg_jobs() -> list[BgJob]:
    """現在実行中の裏エージェント一覧を返す"""
    return [j for j in bg_jobs.values() if j.status == "running"]


async def execute_bg_job(
    job: BgJob,
    message: discord.Message,
    prompt_for_agy: str,
    summary_for_git: str,
) -> None:
    """裏エージェントを独立タスクとして実行し、完了時に Discord へ通知する"""
    try:
        async with get_git_lock():
            pull_warn = await asyncio.to_thread(sync_git_before)
            if pull_warn:
                print(f"⚠️ [bg #{job.job_id}] {pull_warn}")

        ok, reply_text, new_conv_id = await run_agy_prompt(
            prompt_for_agy,
            job.conversation_id,
            timeout_seconds=AGY_BG_TIMEOUT_SECONDS,
            bg_job=job,
        )

        if new_conv_id:
            job.conversation_id = new_conv_id
            bg_convs = load_bg_conversations()
            bg_convs[str(job.job_id)] = new_conv_id
            save_bg_conversations(bg_convs)

        job.finished_at = time.monotonic()
        elapsed_label = format_elapsed(int(job.finished_at - job.started_at))

        if reply_text == "__STOPPED_BY_USER__":
            job.status = "cancelled"
            job.result_note = f"中断 ({elapsed_label})"
            await message.reply(
                f"🛑 **裏エージェント #{job.job_id}** を中断しました（経過: **{elapsed_label}**）。",
                mention_author=False,
            )
            return

        footer = ""
        changed_files: list[str] = []
        if ok and AUTO_GIT_PUSH:
            async with get_git_lock():
                pushed, git_msg, changed_files = await asyncio.to_thread(
                    commit_and_push_changes,
                    summary_for_git or "bg-task",
                    f"discord-bg-#{job.job_id}",
                )
            if changed_files:
                files_preview = ", ".join(f"`{f}`" for f in changed_files[:8])
                if len(changed_files) > 8:
                    files_preview += f" ほか{len(changed_files) - 8}件"
                icon = "📦" if pushed else "⚠️"
                footer = f"\n\n---\n{icon} {git_msg}\n変更ファイル: {files_preview}"

        job.status = "done" if ok else "error"
        job.result_note = f"{'完了' if ok else 'エラー'} ({elapsed_label})"

        header = (
            f"✅ **裏エージェント #{job.job_id} が完了しました！**（所要時間: **{elapsed_label}**）\n"
            f"*(続きを指示するときは `!bg #{job.job_id} <指示>` と送れます)*\n\n"
            if ok
            else f"⚠️ **裏エージェント #{job.job_id} でエラーが発生しました**（経過: **{elapsed_label}**）\n\n"
        )
        await send_long_reply(message, f"{header}{reply_text}{footer}")

        # bot.py 自身が更新され、他に実行中の裏ジョブがない場合のみ自動再起動
        if any("discord-ai-agent/bot.py" in f for f in changed_files):
            if not get_running_bg_jobs():
                print("🔄 [bg] bot.py の更新を検知したため、プロセスを再起動します...")
                os._exit(0)
            else:
                await message.channel.send(
                    "ℹ️ `bot.py` が更新されましたが、他に実行中の裏エージェントがあるため自動再起動を見送りました。完了後に `!restart` で反映できます。"
                )
    except Exception as e:
        job.finished_at = time.monotonic()
        job.status = "error"
        job.result_note = f"例外: {e}"
        elapsed_label = format_elapsed(int(job.finished_at - job.started_at))
        print(f"❌ [bg #{job.job_id}] 例外発生: {e}")
        try:
            await message.reply(
                f"⚠️ **裏エージェント #{job.job_id}** の実行中に予期しないエラーが発生しました（経過: **{elapsed_label}**）:\n```\n{str(e)[:1200]}\n```",
                mention_author=False,
            )
        except Exception:
            pass


@client.event
async def on_ready():
    init_next_bg_job_id()
    bg_timeout_label = "無制限" if AGY_BG_TIMEOUT_SECONDS == 0 else f"{AGY_BG_TIMEOUT_SECONDS}秒"
    print("==========================================")
    print(f"✅ Discord AIエージェント起動: {client.user}")
    print(f"👀 監視チャンネル: #{TARGET_CHANNEL}（およびそのスレッド）")
    print(f"📁 作業リポジトリ: {REPO_DIR}")
    print(f"🤖 実行コマンド: {AGY_BIN} (mode={AGY_MODE}, sandbox=True)")
    print(f"🚀 裏エージェント: 最大{AGY_MAX_BG_JOBS}並列 / タイムアウト={bg_timeout_label}")
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

    lower_text = raw_text.replace("！", "!").replace("／", "/").lower()
    channel_key = str(message.channel.id)

    # 組み込みコマンド: !help
    if lower_text in ("!help", "ヘルプ"):
        await message.reply(
            "📖 **Discord AIエージェント 使い方**\n"
            f"- `#{TARGET_CHANNEL}`（またはこの中のスレッド）にそのまま日本語で指示を書くだけで、`agy` が Mac mini 上で作業して返信します。\n"
            "- 画像・音声・ファイルを添付して送ると、自動で Mac mini 内に保存して `agy` が読み取ります。\n"
            "- ファイルを作成・編集した場合は自動で GitHub (`origin/main`) にコミット＆プッシュします。\n"
            "- **`!bg <指示>`**（または `!裏 <指示>`）: **裏エージェント**を別プロセス＆時間制限なしで起動します（表チャットと同時並行OK・完了時に通知・音声添付もOK）。\n"
            "- **`!bg #<番号> <続きの指示>`** : 過去の裏エージェントの記憶を引き継いで続きを指示します。\n"
            "- **`!jobs`**（または `ジョブ`）: 裏エージェントの稼働状況・経過時間を確認します。\n"
            "- **`!cancel <番号>`**（または `!cancel all`）: 指定した裏エージェントを強制停止します。\n"
            "- `!new` または `リセット` : このチャンネル（スレッド）の会話記憶をリセットします。\n"
            "- `!stop` または `中断` : 表チャットで実行中の作業を強制終了します。\n"
            "- `!status` : `agy`・裏ジョブ・リポジトリの状態を確認します。\n"
            "- `!restart` または `再起動` : Bot自身を再起動して最新コードを反映します。\n"
            "- **スレッド機能** を使うと、話題ごとに別々の会話履歴を保てます！",
            mention_author=False,
        )
        return

    # 組み込みコマンド: !jobs / ジョブ / 裏一覧
    if lower_text in ("!jobs", "jobs", "ジョブ", "裏一覧"):
        if not bg_jobs:
            saved_bg = load_bg_conversations()
            hint = (
                f"\n*(過去の継続可能な裏エージェントID: {', '.join(f'#{k}' for k in sorted(saved_bg.keys(), key=lambda x: int(x) if x.isdigit() else 0)[-5:])})*"
                if saved_bg
                else ""
            )
            await message.reply(
                f"ℹ️ 現在起動中または直近の裏エージェントはありません。`!bg <指示>` で起動できます。{hint}",
                mention_author=False,
            )
            return

        status_icons = {
            "running": "🔄 実行中",
            "done": "✅ 完了",
            "error": "⚠️ エラー",
            "cancelled": "🛑 中断",
        }
        lines = ["📋 **裏エージェント一覧**"]
        now = time.monotonic()
        for jid in sorted(bg_jobs.keys(), reverse=True)[:10]:
            j = bg_jobs[jid]
            end_t = j.finished_at if j.finished_at is not None else now
            elapsed = format_elapsed(int(end_t - j.started_at))
            icon = status_icons.get(j.status, j.status)
            lines.append(f"- **#{j.job_id}** [{icon}] ({elapsed}) — {j.prompt_summary}")
        running_cnt = len(get_running_bg_jobs())
        lines.append(f"\n実行中: **{running_cnt} / {AGY_MAX_BG_JOBS}**（中断は `!cancel <番号>`、続きは `!bg #<番号> <指示>`）")
        await message.reply("\n".join(lines), mention_author=False)
        return

    # 組み込みコマンド: !cancel <番号|all>
    cancel_match = re.match(r"^!(?:cancel|kill)\s+#?(\d+|all)$", lower_text)
    if cancel_match:
        target = cancel_match.group(1)
        if target == "all":
            running = get_running_bg_jobs()
            if not running:
                await message.reply("ℹ️ 現在実行中の裏エージェントはありません。", mention_author=False)
                return
            for j in running:
                j.cancel_requested = True
                if j.proc is not None and j.proc.returncode is None:
                    j.proc.terminate()
            ids_str = ", ".join(f"#{j.job_id}" for j in running)
            await message.reply(f"🛑 実行中の裏エージェント（{ids_str}）に中断シグナルを送りました。", mention_author=False)
            return

        jid = int(target)
        job = bg_jobs.get(jid)
        if not job or job.status != "running":
            await message.reply(f"ℹ️ 裏エージェント **#{jid}** は現在実行中ではありません（確認: `!jobs`）。", mention_author=False)
            return
        job.cancel_requested = True
        if job.proc is not None and job.proc.returncode is None:
            job.proc.terminate()
        await message.reply(f"🛑 裏エージェント **#{jid}** に中断シグナルを送りました。", mention_author=False)
        return

    # 組み込みコマンド: !bg / !裏（汎用バックグラウンド専属エージェント起動）
    bg_parsed = parse_bg_command(raw_text)
    if bg_parsed is not None:
        resume_id, bg_prompt_raw = bg_parsed
        if not bg_prompt_raw and not message.attachments:
            await message.reply(
                "💡 使い方: `!bg <指示内容>`（または音声・画像を添付して `!bg`）\n"
                "過去の裏エージェントに続きを頼む場合: `!bg #<番号> <続きの指示>`",
                mention_author=False,
            )
            return

        running = get_running_bg_jobs()
        if len(running) >= AGY_MAX_BG_JOBS:
            ids_str = ", ".join(f"#{j.job_id}" for j in running)
            await message.reply(
                f"⚠️ 裏エージェントの同時実行上限（**{AGY_MAX_BG_JOBS}件**）に達しています（実行中: {ids_str}）。\n"
                "完了を待つか、`!cancel <番号>` で不要なジョブを停止してから再度お試しください。",
                mention_author=False,
            )
            return

        global next_bg_job_id
        existing_conv_id: Optional[str] = None
        if resume_id is not None:
            if resume_id in bg_jobs and bg_jobs[resume_id].status == "running":
                await message.reply(
                    f"⏳ 裏エージェント **#{resume_id}** はまだ実行中です。完了後に `!bg #{resume_id} ...` で続きを送ってください。",
                    mention_author=False,
                )
                return
            saved_bg = load_bg_conversations()
            existing_conv_id = saved_bg.get(str(resume_id))
            if not existing_conv_id:
                await message.reply(
                    f"⚠️ 裏エージェント **#{resume_id}** の会話履歴が見つかりませんでした。新規起動する場合は `!bg <指示>` と送ってください。",
                    mention_author=False,
                )
                return
            job_id = resume_id
        else:
            job_id = next_bg_job_id
            next_bg_job_id += 1

        prompt_for_agy = await save_attachments_and_build_prompt(message, bg_prompt_raw)
        summary_text = (bg_prompt_raw or "添付ファイルの指示").replace("\n", " ")[:45]
        ch_name = getattr(message.channel, "name", str(message.channel.id))
        job = BgJob(
            job_id=job_id,
            prompt_summary=summary_text,
            channel_name=ch_name,
            started_at=time.monotonic(),
            conversation_id=existing_conv_id,
        )
        bg_jobs[job_id] = job
        job.task = asyncio.create_task(
            execute_bg_job(job, message, prompt_for_agy, bg_prompt_raw or "bg-attachment")
        )

        timeout_label = "なし（完了までじっくり実行）" if AGY_BG_TIMEOUT_SECONDS == 0 else f"最大{AGY_BG_TIMEOUT_SECONDS}秒"
        mode_label = f"（#{job_id} の記憶を引き継ぎ）" if resume_id is not None else "（新規・独立セッション）"
        await message.reply(
            f"🚀 **裏エージェント #{job_id}** を起動しました！{mode_label}\n"
            f"- ⏱️ 時間制限: **{timeout_label}**\n"
            f"- 📊 現在の並列稼働: **{len(get_running_bg_jobs())} / {AGY_MAX_BG_JOBS}**\n"
            f"- 💬 表の `#{TARGET_CHANNEL}` はそのまま別の相談に使えます。完了したらここで通知します！\n"
            f"*(状況確認: `!jobs` ／ 途中停止: `!cancel {job_id}`)*",
            mention_author=False,
        )
        return

    # 組み込みコマンド: !stop / 中断
    if lower_text in ("!stop", "stop", "中断", "ストップ"):
        global stop_requested
        if current_agy_proc is not None and current_agy_proc.returncode is None:
            stop_requested = True
            current_agy_proc.terminate()
            await message.reply("🛑 表チャットで実行中の `agy` 作業を中断しました。次の指示を送れます。", mention_author=False)
        else:
            running_bg = get_running_bg_jobs()
            if running_bg:
                ids_str = ", ".join(f"#{j.job_id}" for j in running_bg)
                await message.reply(
                    f"ℹ️ 表チャットに実行中の作業はありません（裏エージェント {ids_str} が稼働中です。止める場合は `!cancel <番号>` を使用してください）。",
                    mention_author=False,
                )
            else:
                await message.reply("ℹ️ 現在実行中の作業はありません。", mention_author=False)
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
        running_bg = get_running_bg_jobs()
        bg_line = (
            f"{len(running_bg)} / {AGY_MAX_BG_JOBS} 件稼働中（"
            + ", ".join(f"#{j.job_id}" for j in running_bg)
            + "）"
            if running_bg
            else f"0 / {AGY_MAX_BG_JOBS} 件（待機中）"
        )
        await message.reply(
            f"🖥️ **稼働ステータス**\n"
            f"- `agy`: `{agy_ver}`\n"
            f"- 🚀 裏エージェント: {bg_line}\n"
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

                async with get_git_lock():
                    pull_warn = await asyncio.to_thread(sync_git_before)
                    if pull_warn:
                        print(f"⚠️ {pull_warn}")

                prompt_for_agy = await save_attachments_and_build_prompt(message, raw_text)
                ok, reply_text, new_conv_id = await run_agy_prompt(prompt_for_agy, conv_id)

                if new_conv_id:
                    conversations[channel_key] = new_conv_id
                    save_conversations(conversations)

                footer = ""
                changed_files: list[str] = []
                if ok and AUTO_GIT_PUSH:
                    async with get_git_lock():
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
        if reply_text == "__STOPPED_BY_USER__":
            try:
                await status_msg.edit(content=f"🛑 ユーザー指示により中断しました（経過: **{elapsed_total}秒**）")
            except Exception:
                pass
            return

        try:
            done_icon = "✅" if ok else "⚠️"
            await status_msg.edit(content=f"{done_icon} 処理完了（所要時間: **{elapsed_total}秒**）")
        except Exception:
            pass

        prefix = "" if ok else "⚠️ **エラーが発生しました**\n"
        await send_long_reply(message, f"{prefix}{reply_text}{footer}")

        # bot.py 自身が更新された場合は launchd に自動再起動させる（実行中の裏ジョブがないときのみ）
        if any("discord-ai-agent/bot.py" in f for f in changed_files):
            if not get_running_bg_jobs():
                print("🔄 bot.py の更新を検知したため、プロセスを再起動します...")
                os._exit(0)
            else:
                await message.channel.send(
                    "ℹ️ `bot.py` が更新されましたが、実行中の裏エージェントがあるため自動再起動を見送りました。完了後に `!restart` で反映できます。"
                )


if __name__ == "__main__":
    if not TOKEN or TOKEN == "ここにトークンを貼り付け":
        print("❌ エラー: DISCORD_BOT_TOKEN が見つかりません。.env を確認してください。")
    else:
        client.run(TOKEN)
