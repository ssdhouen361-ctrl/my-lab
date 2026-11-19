import asyncio
import os
import subprocess
from typing import Optional
import discord
from dotenv import load_dotenv

# .envファイルから設定を読み込む
load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
TARGET_CHANNEL = os.getenv("DISCORD_CHANNEL_NAME", "mac-control")
PLAYLIST_NAME = os.getenv("PLAYLIST_NAME", "WakeUp")
AUDIO_DEVICE_NAME = os.getenv("AUDIO_DEVICE_NAME", "Mac miniのスピーカー")
WAKEUP_VOLUME = int(os.getenv("WAKEUP_VOLUME", "100"))
SWITCH_AUDIO_BIN = "/opt/homebrew/bin/SwitchAudioSource"
KATRAIN_BIN = "/Users/sasadayuto/my-lab/projects/katago-env/.venv/bin/katrain"
KATRAIN_DIR = "/Users/sasadayuto/my-lab/projects/katago-env"

# 起床アラーム起動前の状態を記憶しておく変数
saved_audio_state: dict = {
    "active": False,           # 現在「起床アラーム再生中」かどうか
    "device": None,            # 元のスピーカー（イヤホン等）の名前
    "output_volume": None,     # 元のMac本体音量（0〜100）
    "output_muted": False,     # 元々ミュートだったかどうか
    "music_volume": None,      # 元のApple Musicアプリ内音量（0〜100）
    "channel": None,           # 通知を送るDiscordチャンネル
}

# Discordのメッセージ内容を読み取る権限（Intents）を設定
intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
monitor_task: Optional[asyncio.Task] = None


def get_current_speaker() -> Optional[str]:
    """現在選択されている出力スピーカー名を取得する"""
    if not os.path.exists(SWITCH_AUDIO_BIN):
        return None
    try:
        res = subprocess.run(
            [SWITCH_AUDIO_BIN, "-c", "-t", "output"],
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def switch_to_speaker(device_name: str) -> tuple[bool, str]:
    """Macの音声出力先を指定したスピーカーに強制的に切り替える"""
    if not os.path.exists(SWITCH_AUDIO_BIN):
        return False, "SwitchAudioSource が見つかりません"
    try:
        result = subprocess.run(
            [SWITCH_AUDIO_BIN, "-s", device_name, "-t", "output"],
            capture_output=True,
            text=True,
            check=True,
        )
        return True, result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return False, e.stderr.strip() or e.stdout.strip()


def get_current_volumes() -> tuple[Optional[int], bool, Optional[int]]:
    """
    現在の（Mac本体音量, ミュート状態, Apple Music内音量）を取得する
    """
    out_vol: Optional[int] = None
    out_muted: bool = False
    music_vol: Optional[int] = None

    try:
        res = subprocess.run(
            [
                "osascript",
                "-e",
                "return (output volume of (get volume settings) as string) & \",\" & (output muted of (get volume settings) as string)",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        parts = res.stdout.strip().split(",")
        if len(parts) == 2:
            out_vol = int(parts[0].strip())
            out_muted = parts[1].strip().lower() == "true"
    except Exception:
        pass

    try:
        res_m = subprocess.run(
            ["osascript", "-e", 'tell application "Music" to get sound volume'],
            capture_output=True,
            text=True,
            check=True,
        )
        music_vol = int(res_m.stdout.strip())
    except Exception:
        pass

    return out_vol, out_muted, music_vol


def set_mac_volume(volume: int, muted: bool = False, music_volume: int = 100) -> tuple[bool, str]:
    """
    Mac本体の音量・ミュート状態・Apple Music内音量をまとめて設定する
    """
    vol = max(0, min(100, volume))
    m_vol = max(0, min(100, music_volume))
    mute_clause = "with output muted" if muted else "without output muted"
    script = (
        f"set volume output volume {vol} {mute_clause}\n"
        f'tell application "Music" to set sound volume to {m_vol}'
    )
    try:
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=True,
        )
        return True, f"{vol}%"
    except subprocess.CalledProcessError as e:
        return False, e.stderr.strip()


def play_apple_music(playlist_name: str) -> tuple[bool, str]:
    """Apple Musicの指定プレイリストを再生する"""
    script = f'tell application "Music" to play playlist "{playlist_name}"'
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=True,
        )
        return True, result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return False, e.stderr.strip()


def is_music_playing() -> bool:
    """現在Apple Musicが再生中（playing）かどうかを調べる"""
    script = 'tell application "System Events" to (name of processes) contains "Music"'
    try:
        proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        if proc.stdout.strip().lower() != "true":
            return False
        state_res = subprocess.run(
            ["osascript", "-e", 'tell application "Music" to get player state as string'],
            capture_output=True,
            text=True,
        )
        return state_res.stdout.strip().lower() == "playing"
    except Exception:
        return False


def restore_previous_audio() -> str:
    """記憶しておいた元の音量とスピーカー設定に戻す"""
    if not saved_audio_state["active"]:
        return ""

    saved_audio_state["active"] = False
    prev_dev = saved_audio_state["device"]
    prev_vol = saved_audio_state["output_volume"]
    prev_muted = saved_audio_state["output_muted"]
    prev_m_vol = saved_audio_state["music_volume"]

    restored_info = []

    # 1. 先に音量を元の大きさ（小音量）に戻す（※スピーカー切替前に下げることで爆音を防ぐ）
    if prev_vol is not None:
        m_vol = prev_m_vol if prev_m_vol is not None else 100
        set_mac_volume(prev_vol, muted=prev_muted, music_volume=m_vol)
        mute_str = " (ミュート)" if prev_muted else ""
        restored_info.append(f"音量: `{prev_vol}%{mute_str}`")

    # 2. 元のスピーカー（イヤホン等）に切り替える
    if prev_dev:
        ok, _ = switch_to_speaker(prev_dev)
        if ok:
            restored_info.append(f"スピーカー: `{prev_dev}`")

    summary = " / ".join(restored_info) if restored_info else "設定なし"
    print(f"🔄 元のオーディオ環境に戻しました -> {summary}")
    return summary


async def watch_music_stop():
    """
    Mac本体（キーボードやマウス）で直接音楽が止められた場合も検知して、
    自動的に元の音量・スピーカーへ戻すバックグラウンド監視ループ
    """
    await client.wait_until_ready()
    while not client.is_closed():
        if saved_audio_state["active"]:
            # 音楽が止まったかどうかチェック
            if not is_music_playing():
                print("🛑 Mac側で音楽の停止を検知しました！元の音量・スピーカーに戻します。")
                channel = saved_audio_state.get("channel")
                summary = restore_previous_audio()
                if channel and summary:
                    try:
                        await channel.send(f"⏹️ 音楽の停止を検知したため、元の設定に戻しました（{summary}）")
                    except Exception:
                        pass
        await asyncio.sleep(2)


@client.event
async def on_ready():
    global monitor_task
    print("==========================================")
    print(f"✅ ログイン成功: {client.user} として起動しました！")
    print(f"👀 監視チャンネル: #{TARGET_CHANNEL}")
    print(f"🔊 起床時スピーカー: {AUDIO_DEVICE_NAME} (音量: {WAKEUP_VOLUME}%)")
    print(f"🎵 起床プレイリスト: {PLAYLIST_NAME}")
    print("🔄 自動復元機能: ON（DiscordでもMac本体でも、音楽を止めると元の音量＆スピーカーに戻ります）")
    print("==========================================")
    if monitor_task is None or monitor_task.done():
        monitor_task = asyncio.create_task(watch_music_stop())


@client.event
async def on_message(message: discord.Message):
    if message.author == client.user:
        return

    if getattr(message.channel, "name", None) != TARGET_CHANNEL:
        return

    raw_text = message.content.strip()
    lower_text = raw_text.lower()

    # ① 起床アラーム用コマンド: 「music wakeup」「MusicWakeUp」「MacWakeUp」すべて対応
    if lower_text in ("music wakeup", "musicwakeup", "mac wakeup", "macwakeup"):
        print(f"🔔 「{raw_text}」を受信しました！")

        # まだ起床モード中でなければ、変更前の現在のスピーカー＆音量を記憶する
        if not saved_audio_state["active"]:
            cur_dev = get_current_speaker()
            cur_vol, cur_muted, cur_m_vol = get_current_volumes()
            saved_audio_state["device"] = cur_dev
            saved_audio_state["output_volume"] = cur_vol
            saved_audio_state["output_muted"] = cur_muted
            saved_audio_state["music_volume"] = cur_m_vol
            saved_audio_state["channel"] = message.channel
            print(f"💾 変更前の状態を記憶しました: スピーカー={cur_dev}, 音量={cur_vol}% (ミュート={cur_muted})")

        # 1. スピーカーを「Mac miniのスピーカー」に切り替え
        spk_ok, spk_msg = switch_to_speaker(AUDIO_DEVICE_NAME)
        if not spk_ok:
            print(f"⚠️ スピーカー切り替え警告: {spk_msg}")

        # 2. 音量を指定値（100%）に設定
        vol_ok, vol_msg = set_mac_volume(WAKEUP_VOLUME, muted=False, music_volume=100)
        if not vol_ok:
            print(f"⚠️ 音量設定警告: {vol_msg}")

        # 3. Apple Musicでプレイリストを再生
        success, detail = play_apple_music(PLAYLIST_NAME)
        if success:
            # 再生が始まるまで少し待ってから監視フラグをONにする
            await asyncio.sleep(1)
            saved_audio_state["active"] = True
            prev_dev_str = saved_audio_state["device"] or "不明"
            prev_vol_str = f"{saved_audio_state['output_volume']}%" if saved_audio_state["output_volume"] is not None else "不明"
            print(f"🎶 『{PLAYLIST_NAME}』の再生に成功しました！（音量: {WAKEUP_VOLUME}%）")
            await message.channel.send(
                f"🌅 **起床アラーム起動 (`music wakeup`)**\n"
                f"🔊 スピーカー: `{AUDIO_DEVICE_NAME}` (音量: `{WAKEUP_VOLUME}%`)\n"
                f"🎵 プレイリスト『**{PLAYLIST_NAME}**』を再生しました！\n"
                f"💡 *音楽を止めると、自動的に元の設定（`{prev_dev_str}` / `{prev_vol_str}`）に戻ります*"
            )
        else:
            print(f"❌ 再生エラー: {detail}")
            restore_previous_audio()
            await message.channel.send(
                f"⚠️ 再生に失敗しました。Apple Musicに『{PLAYLIST_NAME}』があるか確認してください。\nエラー詳細: `{detail}`"
            )

    # ② 音楽停止コマンド: 「music wakeup stop」「MusicWakeUpStop」「MacWakeUpStop」「music stop」すべて対応
    elif lower_text in (
        "music wakeup stop",
        "musicwakeupstop",
        "mac wakeup stop",
        "macwakeupstop",
        "music stop",
        "mac stop",
    ):
        print(f"🛑 「{raw_text}」を受信しました。Apple Musicを一時停止します。")
        subprocess.run(["osascript", "-e", 'tell application "Music" to pause'])
        summary = restore_previous_audio()
        if summary:
            await message.channel.send(f"⏸️ Apple Musicを一時停止し、元の設定に戻しました（{summary}）")
        else:
            await message.channel.send("⏸️ Apple Musicを一時停止しました。")

    # ③ 任意のプレイリスト再生: 「music play <プレイリスト名>」
    elif lower_text.startswith("music play "):
        target_playlist = raw_text[len("music play "):].strip()
        if target_playlist:
            print(f"🎵 「music play {target_playlist}」を受信しました。")
            success, detail = play_apple_music(target_playlist)
            if success:
                await message.channel.send(f"🎵 プレイリスト『**{target_playlist}**』を再生しました！")
            else:
                await message.channel.send(f"⚠️ プレイリスト『{target_playlist}』の再生に失敗しました。")

    # ④ 音量変更コマンド: 「music volume <数値>」
    elif lower_text.startswith("music volume "):
        vol_str = raw_text[len("music volume "):].strip()
        if vol_str.isdigit():
            new_vol = int(vol_str)
            ok, msg = set_mac_volume(new_vol)
            if ok:
                await message.channel.send(f"🔊 Macの音量を **{msg}** に変更しました。")
            else:
                await message.channel.send(f"⚠️ 音量の変更に失敗しました: `{msg}`")

    # ⑤ 囲碁AI（KaTrain / KataGo）起動コマンド: 「katrain」「katago」「囲碁」
    elif lower_text in ("katrain", "katrain start", "katago", "katago start", "囲碁", "囲碁起動"):
        print(f"⚫⚪ 「{raw_text}」を受信しました。KaTrain を起動します。")
        if not os.path.exists(KATRAIN_BIN):
            await message.channel.send("⚠️ KaTrain が見つかりません。セットアップ状況を確認してください。")
            return
        check = subprocess.run(["pgrep", "-f", KATRAIN_BIN], capture_output=True, text=True)
        if check.returncode == 0 and check.stdout.strip():
            # すでに起動中なら最前面に表示
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    'tell application "System Events" to set frontmost of (first process whose name contains "Python" or name contains "katrain") to true',
                ],
                capture_output=True,
            )
            await message.channel.send("⚫⚪ **KaTrain (KataGo)** はすでに起動中です！最前面に表示しました。")
        else:
            env = os.environ.copy()
            env["PATH"] = f"/opt/homebrew/bin:/usr/local/bin:{env.get('PATH', '/usr/bin:/bin')}"
            subprocess.Popen(
                [KATRAIN_BIN],
                cwd=KATRAIN_DIR,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            await message.channel.send("⚫⚪ Mac mini で **KaTrain (KataGo)** を起動しました！Chrome リモートデスクトップからそのまま対局・検討できます。")

    # ⑥ 囲碁AI（KaTrain / KataGo）終了コマンド: 「katrain stop」「katago stop」「囲碁終了」
    elif lower_text in ("katrain stop", "katago stop", "囲碁終了", "囲碁停止"):
        print(f"⏹️ 「{raw_text}」を受信しました。KaTrain を終了します。")
        res = subprocess.run(["pkill", "-f", KATRAIN_BIN], capture_output=True, text=True)
        if res.returncode == 0:
            await message.channel.send("⏹️ **KaTrain (KataGo)** を終了しました。")
        else:
            await message.channel.send("ℹ️ 現在 KaTrain は起動していません。")


if __name__ == "__main__":
    if not TOKEN or TOKEN == "ここにトークンを貼り付け":
        print("❌ エラー: .envファイルに DISCORD_BOT_TOKEN が設定されていません。")
    else:
        client.run(TOKEN)
