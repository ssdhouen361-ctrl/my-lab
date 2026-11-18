package com.mylab.buswidget

import java.util.Calendar

enum class BusRoute(val id: String, val title: String, val shortTitle: String) {
    JR_TO_GNFJ("jr_to_gnfj", "🚌 JR発 ➔ GNFJ（会社行）", "🚌 JR発 ➔ GNFJ"),
    GNFJ_TO_STATION("gnfj_to_station", "🚌 GNFJ発 ➔ JR・京急（帰り）", "🚌 GNFJ発 ➔ 駅"),
    KEIKYU_TO_GNFJ("keikyu_to_gnfj", "🚌 京急発 ➔ GNFJ（会社行）", "🚌 京急発 ➔ GNFJ");

    fun nextRoute(): BusRoute = when (this) {
        JR_TO_GNFJ -> GNFJ_TO_STATION
        GNFJ_TO_STATION -> KEIKYU_TO_GNFJ
        KEIKYU_TO_GNFJ -> JR_TO_GNFJ
    }

    companion object {
        fun fromId(id: String?): BusRoute = entries.firstOrNull { it.id == id } ?: JR_TO_GNFJ
    }
}

data class RawTimetableRow(
    val code: String,
    val gnfjDep: String,
    val keikyuDrop: String,
    val jrDep: String,
    val keikyuBoard: String,
    val gnfjArr: String
)

data class BusScheduleEntry(
    val code: String,
    val depHour: Int,
    val depMinute: Int,
    val depTimeText: String,
    val arrivalOrSubText: String,
    val note: String = ""
) {
    val totalMinutes: Int get() = depHour * 60 + depMinute
}

data class UpcomingBusResult(
    val route: BusRoute,
    val upcomingToday: List<BusScheduleEntry>,
    val firstBusTomorrow: BusScheduleEntry,
    val nextDepartureMillis: Long,
    val isTomorrow: Boolean
)

object BusTimetable {

    // 画像の時刻表（1-1 〜 1-25）完全収録データ
    val ALL_ROWS: List<RawTimetableRow> = listOf(
        RawTimetableRow("1-1",  "07:15", "○", "07:25", "07:26", "07:31"),
        RawTimetableRow("1-2",  "07:50", "○", "08:04", "08:05", "08:10"),
        RawTimetableRow("1-3",  "08:10", "○", "08:18", "－",    "08:23"),
        RawTimetableRow("1-4",  "08:23", "○", "08:32", "－",    "08:37"),
        RawTimetableRow("1-5",  "08:53", "○", "09:03", "09:04", "09:09"),
        RawTimetableRow("1-6",  "09:23", "○", "09:33", "09:34", "09:39"),
        RawTimetableRow("1-7",  "11:00", "○", "11:10", "11:11", "11:16"),
        RawTimetableRow("1-8",  "12:00", "○", "12:10", "12:11", "12:16"),
        RawTimetableRow("1-9",  "13:00", "○", "13:10", "13:11", "13:16"),
        RawTimetableRow("1-10", "13:25", "○", "13:39", "13:40", "13:45"),
        RawTimetableRow("1-11", "13:50", "○", "－",    "○",     ""),
        RawTimetableRow("1-12", "14:10", "○", "14:20", "14:21", "14:26"),
        RawTimetableRow("1-13", "15:10", "○", "15:20", "15:21", "15:26"),
        RawTimetableRow("1-14", "17:10", "○", "－",    "○",     ""),
        RawTimetableRow("1-15", "17:30", "○", "○",     "○",     ""),
        RawTimetableRow("1-16", "17:50", "○", "○",     "○",     ""),
        RawTimetableRow("1-17", "18:10", "○", "○",     "○",     ""),
        RawTimetableRow("1-18", "18:40", "○", "○",     "○",     ""),
        RawTimetableRow("1-19", "19:10", "○", "○",     "○",     ""),
        RawTimetableRow("1-20", "19:43", "○", "○",     "○",     ""),
        RawTimetableRow("1-21", "20:23", "○", "○",     "○",     ""),
        RawTimetableRow("1-22", "20:53", "○", "○",     "○",     ""),
        RawTimetableRow("1-23", "21:23", "○", "21:35", "21:36", "21:41"),
        RawTimetableRow("1-24", "21:53", "○", "○",     "○",     ""),
        RawTimetableRow("1-25", "22:25", "○", "22:36", "22:37", "22:42")
    )

    private fun parseHourMin(timeStr: String): Pair<Int, Int>? {
        if (!timeStr.contains(":")) return null
        val parts = timeStr.split(":")
        val h = parts.getOrNull(0)?.toIntOrNull() ?: return null
        val m = parts.getOrNull(1)?.toIntOrNull() ?: return null
        return h to m
    }

    fun getScheduleForRoute(route: BusRoute): List<BusScheduleEntry> {
        return when (route) {
            BusRoute.JR_TO_GNFJ -> ALL_ROWS.mapNotNull { row ->
                val (h, m) = parseHourMin(row.jrDep) ?: return@mapNotNull null
                val note = if (row.keikyuBoard == "－") "京急通過" else "京急 ${row.keikyuBoard}"
                BusScheduleEntry(
                    code = row.code,
                    depHour = h,
                    depMinute = m,
                    depTimeText = row.jrDep,
                    arrivalOrSubText = "${row.gnfjArr} GNFJ着",
                    note = note
                )
            }

            BusRoute.GNFJ_TO_STATION -> ALL_ROWS.mapNotNull { row ->
                val (h, m) = parseHourMin(row.gnfjDep) ?: return@mapNotNull null
                val isKeikyuOnly = row.jrDep == "－"
                val sub = when {
                    isKeikyuOnly -> "⚠️京急のみ(JR通過)"
                    row.jrDep.contains(":") -> "JR ${row.jrDep}着/発"
                    else -> "京急・JR方面"
                }
                BusScheduleEntry(
                    code = row.code,
                    depHour = h,
                    depMinute = m,
                    depTimeText = row.gnfjDep,
                    arrivalOrSubText = sub,
                    note = if (isKeikyuOnly) "JR通過" else "JR・京急行"
                )
            }

            BusRoute.KEIKYU_TO_GNFJ -> ALL_ROWS.mapNotNull { row ->
                val (h, m) = parseHourMin(row.keikyuBoard) ?: return@mapNotNull null
                BusScheduleEntry(
                    code = row.code,
                    depHour = h,
                    depMinute = m,
                    depTimeText = row.keikyuBoard,
                    arrivalOrSubText = "${row.gnfjArr} GNFJ着",
                    note = "JR ${row.jrDep}発便"
                )
            }
        }
    }

    fun findUpcoming(route: BusRoute, nowMillis: Long = System.currentTimeMillis()): UpcomingBusResult {
        val entries = getScheduleForRoute(route)
        val nowCal = Calendar.getInstance().apply { timeInMillis = nowMillis }

        val upcoming = mutableListOf<BusScheduleEntry>()
        var nextDepMillis: Long? = null

        for (entry in entries) {
            val depCal = (nowCal.clone() as Calendar).apply {
                set(Calendar.HOUR_OF_DAY, entry.depHour)
                set(Calendar.MINUTE, entry.depMinute)
                set(Calendar.SECOND, 0)
                set(Calendar.MILLISECOND, 0)
            }
            if (depCal.timeInMillis > nowMillis) {
                if (nextDepMillis == null) {
                    nextDepMillis = depCal.timeInMillis
                }
                upcoming.add(entry)
            }
        }

        val firstEntry = entries.first()
        if (upcoming.isNotEmpty() && nextDepMillis != null) {
            return UpcomingBusResult(
                route = route,
                upcomingToday = upcoming,
                firstBusTomorrow = firstEntry,
                nextDepartureMillis = nextDepMillis,
                isTomorrow = false
            )
        }

        // 本日の最終便が終了している場合は明日の始発へのカウントダウンを返す
        val tomorrowCal = (nowCal.clone() as Calendar).apply {
            add(Calendar.DAY_OF_YEAR, 1)
            set(Calendar.HOUR_OF_DAY, firstEntry.depHour)
            set(Calendar.MINUTE, firstEntry.depMinute)
            set(Calendar.SECOND, 0)
            set(Calendar.MILLISECOND, 0)
        }

        return UpcomingBusResult(
            route = route,
            upcomingToday = emptyList(),
            firstBusTomorrow = firstEntry,
            nextDepartureMillis = tomorrowCal.timeInMillis,
            isTomorrow = true
        )
    }
}
