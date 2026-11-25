package com.mylab.tactictap

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.SystemClock
import androidx.core.app.NotificationCompat
import androidx.wear.ongoing.OngoingActivity
import androidx.wear.ongoing.Status

object OngoingTimerHelper {
    private const val CHANNEL_ID = "tactictap_running_timer"
    private const val NOTIFICATION_ID = 2001

    fun createNotificationChannel(context: Context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "TacTicTap タイマー実行中",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "文字盤下部にタイマーのカウントダウンピルを表示します"
                setShowBadge(false)
            }
            val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as? NotificationManager
            nm?.createNotificationChannel(channel)
        }
    }

    /**
     * タイマー開始時にWear OSの文字盤下部ポップアップ（Ongoing Activity ピル）を表示する
     */
    fun showOngoingPill(context: Context, remainingSeconds: Long) {
        createNotificationChannel(context)
        val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as? NotificationManager ?: return

        val targetEpochMs = System.currentTimeMillis() + (remainingSeconds * 1000L)
        val targetElapsedRealtimeMs = SystemClock.elapsedRealtime() + (remainingSeconds * 1000L)

        val openIntent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        val pendingIntent = PendingIntent.getActivity(
            context,
            0,
            openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val notificationBuilder = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentTitle("TacTicTap タイマー")
            .setContentText("カウントダウン中...")
            .setOngoing(true)
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setContentIntent(pendingIntent)

        // タイマー専用ステータステンプレート（文字盤下部にリアルタイムカウントダウン表示）
        val status = Status.Builder()
            .addTemplate("#time#")
            .addPart("time", Status.TimerPart(targetElapsedRealtimeMs))
            .build()

        val ongoingActivity = OngoingActivity.Builder(context, NOTIFICATION_ID, notificationBuilder)
            .setAnimatedIcon(R.drawable.ic_launcher_foreground)
            .setStaticIcon(R.drawable.ic_launcher_foreground)
            .setTouchIntent(pendingIntent)
            .setStatus(status)
            .build()

        ongoingActivity.apply(context)
        nm.notify(NOTIFICATION_ID, notificationBuilder.build())
    }

    /**
     * タイマー終了・一時停止・リセット時に文字盤下部ポップアップを消去する
     */
    fun hideOngoingPill(context: Context) {
        val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as? NotificationManager ?: return
        nm.cancel(NOTIFICATION_ID)
    }
}
