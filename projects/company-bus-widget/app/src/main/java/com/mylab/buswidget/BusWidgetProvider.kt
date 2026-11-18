package com.mylab.buswidget

import android.app.AlarmManager
import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.os.SystemClock
import android.view.View
import android.widget.RemoteViews

class BusWidgetProvider : AppWidgetProvider() {

    companion object {
        const val ACTION_REFRESH = "com.mylab.buswidget.ACTION_REFRESH"
        const val ACTION_TOGGLE_ROUTE = "com.mylab.buswidget.ACTION_TOGGLE_ROUTE"
        const val ACTION_AUTO_TICK = "com.mylab.buswidget.ACTION_AUTO_TICK"

        private const val PREFS_NAME = "bus_widget_prefs"
        private const val KEY_ROUTE = "selected_route"

        fun getSavedRoute(context: Context): BusRoute {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return BusRoute.fromId(prefs.getString(KEY_ROUTE, BusRoute.JR_TO_GNFJ.id))
        }

        fun saveRoute(context: Context, route: BusRoute) {
            context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .edit()
                .putString(KEY_ROUTE, route.id)
                .apply()
        }

        fun updateAllWidgets(context: Context) {
            val manager = AppWidgetManager.getInstance(context)
            val ids = manager.getAppWidgetIds(ComponentName(context, BusWidgetProvider::class.java))
            for (id in ids) {
                val options = manager.getAppWidgetOptions(id)
                updateSingleWidget(context, manager, id, options)
            }
            scheduleNextDepartureAlarm(context)
        }

        fun updateSingleWidget(
            context: Context,
            appWidgetManager: AppWidgetManager,
            appWidgetId: Int,
            options: Bundle?
        ) {
            val route = getSavedRoute(context)
            val nowMillis = System.currentTimeMillis()
            val result = BusTimetable.findUpcoming(route, nowMillis)

            val views = RemoteViews(context.packageName, R.layout.widget_bus_countdown)
            views.setTextViewText(R.id.tv_route_title, route.shortTitle)

            // 往復切替ボタン（JR発 ⇄ GNFJ発）
            val toggleIntent = Intent(context, BusWidgetProvider::class.java).apply {
                action = ACTION_TOGGLE_ROUTE
            }
            views.setOnClickPendingIntent(
                R.id.btn_toggle_route,
                PendingIntent.getBroadcast(
                    context,
                    1001,
                    toggleIntent,
                    PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
                )
            )

            // カウントダウン部分をタップすると最新状態に手動更新
            val refreshIntent = Intent(context, BusWidgetProvider::class.java).apply {
                action = ACTION_REFRESH
            }
            views.setOnClickPendingIntent(
                R.id.right_countdown_area,
                PendingIntent.getBroadcast(
                    context,
                    1002,
                    refreshIntent,
                    PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
                )
            )

            // メイン領域をタップすると全体時刻表アプリを起動
            val openAppIntent = Intent(context, MainActivity::class.java)
            views.setOnClickPendingIntent(
                R.id.main_body,
                PendingIntent.getActivity(
                    context,
                    1003,
                    openAppIntent,
                    PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
                )
            )

            val remainMillis = (result.nextDepartureMillis - nowMillis).coerceAtLeast(0L)
            val chronometerBase = SystemClock.elapsedRealtime() + remainMillis
            views.setChronometerCountDown(R.id.chronometer_countdown, true)

            if (!result.isTomorrow && result.upcomingToday.isNotEmpty()) {
                val first = result.upcomingToday[0]
                views.setTextViewText(R.id.tv_next_badge, "次発")
                views.setTextViewText(R.id.tv_next_time, "${first.depTimeText}発")
                views.setTextViewText(R.id.tv_next_sub, first.shortArrText)
                views.setTextViewText(R.id.tv_countdown_label, "発車まであと")
                views.setViewVisibility(R.id.chronometer_countdown, View.VISIBLE)
                views.setViewVisibility(R.id.tv_status_fallback, View.GONE)
                views.setChronometer(R.id.chronometer_countdown, chronometerBase, null, true)

                val second = result.upcomingToday.getOrNull(1)
                if (second != null) {
                    views.setTextViewText(
                        R.id.tv_second_info,
                        "${second.depTimeText}発 ➔ ${second.shortArrText}"
                    )
                } else {
                    views.setTextViewText(R.id.tv_second_info, "次発が本日の最終便です")
                }

                val third = result.upcomingToday.getOrNull(2)
                if (third != null) {
                    views.setTextViewText(
                        R.id.tv_third_info,
                        "${third.depTimeText}発 ➔ ${third.shortArrText}"
                    )
                } else {
                    views.setTextViewText(
                        R.id.tv_third_info,
                        "明日始発 ${result.firstBusTomorrow.depTimeText}発 ➔ ${result.firstBusTomorrow.shortArrText}"
                    )
                }
            } else {
                val tomorrowFirst = result.firstBusTomorrow
                views.setTextViewText(R.id.tv_next_badge, "明日始発")
                views.setTextViewText(R.id.tv_next_time, "${tomorrowFirst.depTimeText}発")
                views.setTextViewText(R.id.tv_next_sub, tomorrowFirst.shortArrText)
                views.setTextViewText(R.id.tv_countdown_label, "始発まであと")
                views.setViewVisibility(R.id.chronometer_countdown, View.VISIBLE)
                views.setViewVisibility(R.id.tv_status_fallback, View.GONE)
                views.setChronometer(R.id.chronometer_countdown, chronometerBase, null, true)

                val allEntries = BusTimetable.getScheduleForRoute(route)
                val secondTomorrow = allEntries.getOrNull(1)
                val thirdTomorrow = allEntries.getOrNull(2)
                views.setTextViewText(
                    R.id.tv_second_info,
                    if (secondTomorrow != null) "${secondTomorrow.depTimeText}発 ➔ ${secondTomorrow.shortArrText}"
                    else "タップで時刻表を表示"
                )
                views.setTextViewText(
                    R.id.tv_third_info,
                    if (thirdTomorrow != null) "${thirdTomorrow.depTimeText}発 ➔ ${thirdTomorrow.shortArrText}"
                    else ""
                )
            }

            // Galaxy Home Up 自由リサイズ対応
            val minHeightDp = options?.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_HEIGHT, 140) ?: 140
            when {
                minHeightDp < 95 -> {
                    views.setViewVisibility(R.id.upcoming_container, View.GONE)
                }
                minHeightDp < 130 -> {
                    views.setViewVisibility(R.id.upcoming_container, View.VISIBLE)
                    views.setViewVisibility(R.id.row_second_bus, View.VISIBLE)
                    views.setViewVisibility(R.id.row_third_bus, View.GONE)
                }
                else -> {
                    views.setViewVisibility(R.id.upcoming_container, View.VISIBLE)
                    views.setViewVisibility(R.id.row_second_bus, View.VISIBLE)
                    views.setViewVisibility(R.id.row_third_bus, View.VISIBLE)
                }
            }

            appWidgetManager.updateAppWidget(appWidgetId, views)
        }

        private fun scheduleNextDepartureAlarm(context: Context) {
            val alarmManager = context.getSystemService(Context.ALARM_SERVICE) as? AlarmManager ?: return
            val route = getSavedRoute(context)
            val result = BusTimetable.findUpcoming(route)
            val triggerAt = result.nextDepartureMillis + 1000L

            val intent = Intent(context, BusWidgetProvider::class.java).apply {
                action = ACTION_AUTO_TICK
            }
            val pending = PendingIntent.getBroadcast(
                context,
                2001,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )

            try {
                alarmManager.setExactAndAllowWhileIdle(AlarmManager.RTC, triggerAt, pending)
            } catch (_: SecurityException) {
                alarmManager.set(AlarmManager.RTC, triggerAt, pending)
            }
        }
    }

    override fun onUpdate(
        context: Context,
        appWidgetManager: AppWidgetManager,
        appWidgetIds: IntArray
    ) {
        for (appWidgetId in appWidgetIds) {
            val options = appWidgetManager.getAppWidgetOptions(appWidgetId)
            updateSingleWidget(context, appWidgetManager, appWidgetId, options)
        }
        scheduleNextDepartureAlarm(context)
    }

    override fun onAppWidgetOptionsChanged(
        context: Context,
        appWidgetManager: AppWidgetManager,
        appWidgetId: Int,
        newOptions: Bundle
    ) {
        super.onAppWidgetOptionsChanged(context, appWidgetManager, appWidgetId, newOptions)
        updateSingleWidget(context, appWidgetManager, appWidgetId, newOptions)
    }

    override fun onReceive(context: Context, intent: Intent) {
        super.onReceive(context, intent)
        when (intent.action) {
            ACTION_TOGGLE_ROUTE -> {
                val next = getSavedRoute(context).toggleRoundTrip()
                saveRoute(context, next)
                updateAllWidgets(context)
            }
            ACTION_REFRESH,
            ACTION_AUTO_TICK,
            Intent.ACTION_TIME_CHANGED,
            Intent.ACTION_TIMEZONE_CHANGED,
            Intent.ACTION_DATE_CHANGED -> {
                updateAllWidgets(context)
            }
        }
    }
}
