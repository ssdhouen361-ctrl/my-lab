package com.mylab.buswidget

import android.app.Activity
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.TypedValue
import android.view.Gravity
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

class MainActivity : Activity() {

    private val handler = Handler(Looper.getMainLooper())
    private lateinit var tvRouteHeader: TextView
    private lateinit var tvMainNextTime: TextView
    private lateinit var tvMainCountdown: TextView
    private lateinit var tvMainSubInfo: TextView
    private lateinit var scheduleListContainer: LinearLayout
    private val routeButtons = mutableMapOf<BusRoute, TextView>()

    private val tickRunnable = object : Runnable {
        override fun run() {
            refreshUi()
            handler.postDelayed(this, 1000L)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(buildRootLayout())
    }

    override fun onResume() {
        super.onResume()
        BusWidgetProvider.updateAllWidgets(this)
        handler.post(tickRunnable)
    }

    override fun onPause() {
        super.onPause()
        handler.removeCallbacks(tickRunnable)
    }

    private fun dp(value: Int): Int =
        TypedValue.applyDimension(
            TypedValue.COMPLEX_UNIT_DIP,
            value.toFloat(),
            resources.displayMetrics
        ).toInt()

    private fun roundedBg(fillColor: Int, radiusDp: Int, strokeColor: Int = 0): GradientDrawable =
        GradientDrawable().apply {
            setColor(fillColor)
            cornerRadius = dp(radiusDp).toFloat()
            if (strokeColor != 0) {
                setStroke(dp(1), strokeColor)
            }
        }

    private fun buildRootLayout(): ScrollView {
        val scroll = ScrollView(this).apply {
            setBackgroundColor(Color.parseColor("#0F172A"))
        }

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(20), dp(16), dp(32))
        }

        val title = TextView(this).apply {
            text = "🚌 社バス カウントダウン (GNFJ)"
            setTextColor(Color.WHITE)
            textSize = 20f
            setTypeface(typeface, Typeface.BOLD)
        }
        root.addView(title)

        val subtitle = TextView(this).apply {
            text = "ルートを切り替えるとホーム画面のウィジェットも連動して切り替わります"
            setTextColor(Color.parseColor("#94A3B8"))
            textSize = 12f
            setPadding(0, dp(4), 0, dp(14))
        }
        root.addView(subtitle)

        // ルート切替タブ
        val tabRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply { bottomMargin = dp(14) }
        }

        BusRoute.entries.forEachIndexed { idx, route ->
            val btn = TextView(this).apply {
                text = when (route) {
                    BusRoute.JR_TO_GNFJ -> "JR発➔会社"
                    BusRoute.GNFJ_TO_STATION -> "会社発➔駅"
                    BusRoute.KEIKYU_TO_GNFJ -> "京急発➔会社"
                }
                gravity = Gravity.CENTER
                textSize = 13f
                setTypeface(typeface, Typeface.BOLD)
                setPadding(dp(8), dp(10), dp(8), dp(10))
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).apply {
                    if (idx > 0) leftMargin = dp(6)
                }
                setOnClickListener {
                    BusWidgetProvider.saveRoute(this@MainActivity, route)
                    BusWidgetProvider.updateAllWidgets(this@MainActivity)
                    refreshUi()
                }
            }
            routeButtons[route] = btn
            tabRow.addView(btn)
        }
        root.addView(tabRow)

        // Yahoo!乗換案内風メインカウントダウンカード
        val card = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            background = roundedBg(Color.parseColor("#1E293B"), 18, Color.parseColor("#334155"))
            setPadding(dp(16), dp(14), dp(16), dp(16))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply { bottomMargin = dp(18) }
        }

        tvRouteHeader = TextView(this).apply {
            setTextColor(Color.parseColor("#38BDF8"))
            textSize = 14f
            setTypeface(typeface, Typeface.BOLD)
        }
        card.addView(tvRouteHeader)

        tvMainNextTime = TextView(this).apply {
            setTextColor(Color.WHITE)
            textSize = 24f
            setTypeface(typeface, Typeface.BOLD)
            setPadding(0, dp(6), 0, dp(2))
        }
        card.addView(tvMainNextTime)

        tvMainCountdown = TextView(this).apply {
            setTextColor(Color.parseColor("#FBBF24"))
            textSize = 36f
            setTypeface(typeface, Typeface.BOLD)
            setPadding(0, dp(2), 0, dp(4))
        }
        card.addView(tvMainCountdown)

        tvMainSubInfo = TextView(this).apply {
            setTextColor(Color.parseColor("#CBD5E1"))
            textSize = 13f
        }
        card.addView(tvMainSubInfo)
        root.addView(card)

        // 時刻表一覧見出し
        val listHeader = TextView(this).apply {
            text = "📋 時刻表一覧（次発をハイライト表示）"
            setTextColor(Color.parseColor("#E2E8F0"))
            textSize = 15f
            setTypeface(typeface, Typeface.BOLD)
            setPadding(0, 0, 0, dp(8))
        }
        root.addView(listHeader)

        scheduleListContainer = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
        }
        root.addView(scheduleListContainer)

        scroll.addView(root)
        return scroll
    }

    private fun refreshUi() {
        val currentRoute = BusWidgetProvider.getSavedRoute(this)
        val nowMillis = System.currentTimeMillis()
        val result = BusTimetable.findUpcoming(currentRoute, nowMillis)

        routeButtons.forEach { (route, btn) ->
            val selected = route == currentRoute
            btn.background = roundedBg(
                if (selected) Color.parseColor("#0D6EFD") else Color.parseColor("#1E293B"),
                12,
                if (selected) Color.parseColor("#60A5FA") else Color.parseColor("#334155")
            )
            btn.setTextColor(if (selected) Color.WHITE else Color.parseColor("#94A3B8"))
        }

        tvRouteHeader.text = currentRoute.title

        val remainSec = ((result.nextDepartureMillis - nowMillis) / 1000L).coerceAtLeast(0L)
        val h = remainSec / 3600
        val m = (remainSec % 3600) / 60
        val s = remainSec % 60
        val countdownStr = if (h > 0) {
            String.format("あと %d時間%02d分%02d秒", h, m, s)
        } else {
            String.format("あと %02d分%02d秒", m, s)
        }

        val activeCode: String?
        if (!result.isTomorrow && result.upcomingToday.isNotEmpty()) {
            val nextBus = result.upcomingToday[0]
            activeCode = nextBus.code
            tvMainNextTime.text = "次発 ${nextBus.depTimeText}発（${nextBus.code}便）"
            tvMainCountdown.text = countdownStr
            val second = result.upcomingToday.getOrNull(1)
            tvMainSubInfo.text = buildString {
                append("${nextBus.arrivalOrSubText} / ${nextBus.note}")
                if (second != null) {
                    append("\n次々発: ${second.depTimeText}発 (${second.code}便) ➔ ${second.arrivalOrSubText}")
                }
            }
        } else {
            val first = result.firstBusTomorrow
            activeCode = null
            tvMainNextTime.text = "本日の運行終了（明日始発 ${first.depTimeText}発）"
            tvMainCountdown.text = countdownStr
            tvMainSubInfo.text = "明日の始発 (${first.code}便) ➔ ${first.arrivalOrSubText}"
        }

        scheduleListContainer.removeAllViews()
        val entries = BusTimetable.getScheduleForRoute(currentRoute)
        for (entry in entries) {
            val isNext = entry.code == activeCode
            val rowView = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
                background = roundedBg(
                    if (isNext) Color.parseColor("#1E3A8A") else Color.parseColor("#1E293B"),
                    10,
                    if (isNext) Color.parseColor("#FBBF24") else 0
                )
                setPadding(dp(12), dp(10), dp(12), dp(10))
                layoutParams = LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                ).apply { bottomMargin = dp(6) }
            }

            val codeTv = TextView(this).apply {
                text = if (isNext) "▶ ${entry.code}" else entry.code
                setTextColor(if (isNext) Color.parseColor("#FBBF24") else Color.parseColor("#94A3B8"))
                textSize = 13f
                setTypeface(typeface, Typeface.BOLD)
                layoutParams = LinearLayout.LayoutParams(dp(64), LinearLayout.LayoutParams.WRAP_CONTENT)
            }

            val timeTv = TextView(this).apply {
                text = "${entry.depTimeText}発"
                setTextColor(Color.WHITE)
                textSize = 16f
                setTypeface(typeface, Typeface.BOLD)
                layoutParams = LinearLayout.LayoutParams(dp(86), LinearLayout.LayoutParams.WRAP_CONTENT)
            }

            val detailTv = TextView(this).apply {
                text = "${entry.arrivalOrSubText} (${entry.note})"
                setTextColor(Color.parseColor("#CBD5E1"))
                textSize = 12f
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            }

            rowView.addView(codeTv)
            rowView.addView(timeTv)
            rowView.addView(detailTv)
            scheduleListContainer.addView(rowView)
        }
    }
}
