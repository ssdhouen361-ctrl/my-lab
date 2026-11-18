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
    private lateinit var tableContainer: LinearLayout
    private lateinit var btnViewFullTable: TextView
    private lateinit var btnViewRouteOnly: TextView
    private val routeButtons = mutableMapOf<BusRoute, TextView>()
    private var showFullTable: Boolean = true

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
            text = "社バス カウントダウン (GNFJ)"
            setTextColor(Color.WHITE)
            textSize = 20f
            setTypeface(typeface, Typeface.BOLD)
        }
        root.addView(title)

        val subtitle = TextView(this).apply {
            text = "方面を切り替えるとホーム画面のウィジェットも連動して切り替わります"
            setTextColor(Color.parseColor("#94A3B8"))
            textSize = 12f
            setPadding(0, dp(4), 0, dp(12))
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
                    BusRoute.JR_TO_GNFJ -> "JR発 ➔ GNFJ"
                    BusRoute.GNFJ_TO_STATION -> "GNFJ発 ➔ 駅"
                    BusRoute.KEIKYU_TO_GNFJ -> "京急発 ➔ GNFJ"
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

        // メインカウントダウンカード
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
            textSize = 15f
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
            textSize = 34f
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

        // 時刻表表示モード切替（「時刻表全体（全列）」/「選択ルートのみ」）
        val modeRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply { bottomMargin = dp(10) }
        }

        btnViewFullTable = TextView(this).apply {
            text = "📊 時刻表全体（全便表）"
            gravity = Gravity.CENTER
            textSize = 13f
            setTypeface(typeface, Typeface.BOLD)
            setPadding(dp(10), dp(8), dp(10), dp(8))
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).apply {
                rightMargin = dp(6)
            }
            setOnClickListener {
                showFullTable = true
                refreshUi()
            }
        }

        btnViewRouteOnly = TextView(this).apply {
            text = "📋 選択方面のみ"
            gravity = Gravity.CENTER
            textSize = 13f
            setTypeface(typeface, Typeface.BOLD)
            setPadding(dp(10), dp(8), dp(10), dp(8))
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            setOnClickListener {
                showFullTable = false
                refreshUi()
            }
        }

        modeRow.addView(btnViewFullTable)
        modeRow.addView(btnViewRouteOnly)
        root.addView(modeRow)

        tableContainer = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
        }
        root.addView(tableContainer)

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

        btnViewFullTable.background = roundedBg(
            if (showFullTable) Color.parseColor("#0284C7") else Color.parseColor("#1E293B"),
            10,
            if (showFullTable) Color.parseColor("#38BDF8") else Color.parseColor("#334155")
        )
        btnViewFullTable.setTextColor(if (showFullTable) Color.WHITE else Color.parseColor("#94A3B8"))

        btnViewRouteOnly.background = roundedBg(
            if (!showFullTable) Color.parseColor("#0284C7") else Color.parseColor("#1E293B"),
            10,
            if (!showFullTable) Color.parseColor("#38BDF8") else Color.parseColor("#334155")
        )
        btnViewRouteOnly.setTextColor(if (!showFullTable) Color.WHITE else Color.parseColor("#94A3B8"))

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
            tvMainNextTime.text = "次発 ${nextBus.depTimeText}発 ➔ ${nextBus.shortArrText}"
            tvMainCountdown.text = countdownStr
            val second = result.upcomingToday.getOrNull(1)
            val third = result.upcomingToday.getOrNull(2)
            tvMainSubInfo.text = buildString {
                append(nextBus.detailText)
                if (second != null) {
                    append("\n次々発: ${second.depTimeText}発 ➔ ${second.shortArrText}")
                }
                if (third != null) {
                    append("  /  3本目: ${third.depTimeText}発 ➔ ${third.shortArrText}")
                }
            }
        } else {
            val first = result.firstBusTomorrow
            activeCode = first.code
            tvMainNextTime.text = "明日始発 ${first.depTimeText}発 ➔ ${first.shortArrText}"
            tvMainCountdown.text = countdownStr
            tvMainSubInfo.text = "本日の運行は終了しました（明日の始発までカウントダウン中）"
        }

        tableContainer.removeAllViews()
        if (showFullTable) {
            renderFullTimetable(activeCode, currentRoute)
        } else {
            renderRouteScheduleList(currentRoute, activeCode)
        }
    }

    /** 元の時刻表画像と同じ5列（GNFJ発 | 京急(降) | JR発 | 京急(乗) | GNFJ着）の全体表を描画 */
    private fun renderFullTimetable(activeCode: String?, currentRoute: BusRoute) {
        val tableCard = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            background = roundedBg(Color.parseColor("#1E293B"), 12, Color.parseColor("#334155"))
            setPadding(dp(2), dp(2), dp(2), dp(6))
        }

        // ヘッダー行
        val headerRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            background = roundedBg(Color.parseColor("#0D6EFD"), 10, 0)
            setPadding(dp(6), dp(10), dp(6), dp(10))
        }
        val headers = listOf("GNFJ発", "京急(降)", "JR発", "京急(乗)", "GNFJ着")
        headers.forEachIndexed { idx, hText ->
            val isHighlightedCol =
                (currentRoute == BusRoute.GNFJ_TO_STATION && idx == 0) ||
                (currentRoute == BusRoute.JR_TO_GNFJ && idx == 2) ||
                (currentRoute == BusRoute.KEIKYU_TO_GNFJ && idx == 3)
            val tv = TextView(this).apply {
                text = hText
                gravity = Gravity.CENTER
                setTextColor(if (isHighlightedCol) Color.parseColor("#FDE047") else Color.WHITE)
                textSize = 12f
                setTypeface(typeface, Typeface.BOLD)
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            }
            headerRow.addView(tv)
        }
        tableCard.addView(headerRow)

        // 全25便のデータ行
        BusTimetable.ALL_ROWS.forEachIndexed { index, row ->
            val isNextRow = row.code == activeCode
            val bgColor = when {
                isNextRow -> Color.parseColor("#1E3A8A")
                index % 2 == 0 -> Color.parseColor("#0F172A")
                else -> Color.parseColor("#1E293B")
            }

            val tr = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
                setBackgroundColor(bgColor)
                setPadding(dp(6), dp(8), dp(6), dp(8))
            }

            val cols = listOf(
                row.gnfjDep,
                row.keikyuDrop,
                row.jrDep,
                row.keikyuBoard,
                if (row.gnfjArr.isEmpty()) "－" else row.gnfjArr
            )

            cols.forEachIndexed { colIdx, cellText ->
                val isTargetCol =
                    (currentRoute == BusRoute.GNFJ_TO_STATION && colIdx == 0) ||
                    (currentRoute == BusRoute.JR_TO_GNFJ && colIdx == 2) ||
                    (currentRoute == BusRoute.KEIKYU_TO_GNFJ && colIdx == 3)

                val tv = TextView(this).apply {
                    text = if (isNextRow && isTargetCol) "▶$cellText" else cellText
                    gravity = Gravity.CENTER
                    textSize = 13f
                    setTypeface(
                        typeface,
                        if (isNextRow || isTargetCol) Typeface.BOLD else Typeface.NORMAL
                    )
                    setTextColor(
                        when {
                            isNextRow && isTargetCol -> Color.parseColor("#FBBF24")
                            isNextRow -> Color.WHITE
                            cellText == "－" -> Color.parseColor("#64748B")
                            isTargetCol -> Color.parseColor("#38BDF8")
                            else -> Color.parseColor("#E2E8F0")
                        }
                    )
                    layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
                }
                tr.addView(tv)
            }
            tableCard.addView(tr)
        }

        tableContainer.addView(tableCard)
    }

    private fun renderRouteScheduleList(currentRoute: BusRoute, activeCode: String?) {
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
                setPadding(dp(14), dp(10), dp(14), dp(10))
                layoutParams = LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                ).apply { bottomMargin = dp(6) }
            }

            val timeTv = TextView(this).apply {
                text = if (isNext) "▶ ${entry.depTimeText}発" else "${entry.depTimeText}発"
                setTextColor(if (isNext) Color.parseColor("#FBBF24") else Color.WHITE)
                textSize = 16f
                setTypeface(typeface, Typeface.BOLD)
                layoutParams = LinearLayout.LayoutParams(dp(105), LinearLayout.LayoutParams.WRAP_CONTENT)
            }

            val detailTv = TextView(this).apply {
                text = entry.detailText
                setTextColor(Color.parseColor("#CBD5E1"))
                textSize = 13f
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            }

            rowView.addView(timeTv)
            rowView.addView(detailTv)
            tableContainer.addView(rowView)
        }
    }
}
