package com.mylab.tactictap

import android.content.Context
import android.os.Bundle
import android.os.VibrationEffect
import android.os.Vibrator
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.wear.compose.material.Text
import kotlinx.coroutines.delay
import kotlin.math.abs

enum class AppState {
    SETUP,
    RUNNING,
    PAUSED,
    RINGING,
    SETTINGS
}

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        val isAlarmMode = intent?.component?.className?.contains("AlarmActivity") == true
        
        setContent {
            TacTicTapApp(initialAlarmMode = isAlarmMode)
        }
    }
}

@Composable
fun TacTicTapApp(initialAlarmMode: Boolean) {
    val context = LocalContext.current
    val prefs = remember { context.getSharedPreferences("tactictap_prefs", Context.MODE_PRIVATE) }
    val vibrator = remember { context.getSystemService(Vibrator::class.java) }

    fun playClickHaptic(isDouble: Boolean = false) {
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.Q) {
            val effect = if (isDouble) {
                VibrationEffect.createPredefined(VibrationEffect.EFFECT_DOUBLE_CLICK)
            } else {
                VibrationEffect.createPredefined(VibrationEffect.EFFECT_CLICK)
            }
            vibrator?.vibrate(effect)
        } else {
            @Suppress("DEPRECATION")
            vibrator?.vibrate(if (isDouble) 50 else 25)
        }
    }

    var currentThemeIndex by remember { 
        mutableIntStateOf(prefs.getInt("theme_index", 0)) 
    }
    val currentTheme = AppTheme.values()[currentThemeIndex.coerceIn(0, AppTheme.values().size - 1)]

    // 操作設定（左右反転、上下反転）
    // デフォルト: 
    //   左右: 左=次桁(+1), 右=前桁(-1)  (invertHorizontal=true で 右=次桁, 左=前桁)
    //   上下: 上=確定(即スタート), 下=リセット (invertVertical=true で 下=確定, 上=リセット)
    var invertHorizontal by remember { mutableStateOf(prefs.getBoolean("invert_h", false)) }
    var invertVertical by remember { mutableStateOf(prefs.getBoolean("invert_v", false)) }

    fun saveSettings() {
        prefs.edit()
            .putInt("theme_index", currentThemeIndex)
            .putBoolean("invert_h", invertHorizontal)
            .putBoolean("invert_v", invertVertical)
            .apply()
    }
    
    var appState by remember { mutableStateOf(AppState.SETUP) }
    var digits by remember { mutableStateOf(intArrayOf(0, 0, 0, 0)) } // d0, d1, d2, d3
    var activeDigitIndex by remember { mutableIntStateOf(0) } // 0..3
    var remainingSeconds by remember { mutableLongStateOf(0L) }

    // Colon blink animation for RUNNING state
    val infiniteTransition = rememberInfiniteTransition(label = "colon")
    val colonAlpha by infiniteTransition.animateFloat(
        initialValue = 1f,
        targetValue = 0.15f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 500, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "colonAlpha"
    )

    // Countdown Timer Loop
    LaunchedEffect(appState) {
        if (appState == AppState.RUNNING) {
            while (remainingSeconds > 0 && appState == AppState.RUNNING) {
                delay(1000L)
                remainingSeconds--
            }
            if (remainingSeconds <= 0L && appState == AppState.RUNNING) {
                appState = AppState.RINGING
                OngoingTimerHelper.hideOngoingPill(context)
                SoundAndVibeHelper.startAlarmSoundAndVibe(context)
            }
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(currentTheme.bg)
            .pointerInput(appState, activeDigitIndex, invertHorizontal, invertVertical) {
                var totalDragX = 0f
                var totalDragY = 0f

                detectDragGestures(
                    onDragStart = {
                        totalDragX = 0f
                        totalDragY = 0f
                    },
                    onDrag = { change, dragAmount ->
                        change.consume()
                        totalDragX += dragAmount.x
                        totalDragY += dragAmount.y
                    },
                    onDragEnd = {
                        if (appState == AppState.SETTINGS) return@detectDragGestures

                        val threshold = 35f
                        val isHorizontal = abs(totalDragX) > abs(totalDragY)

                        if (isHorizontal) {
                            val isLeft = totalDragX < -threshold
                            val isRight = totalDragX > threshold

                            if (isLeft || isRight) {
                                // 左右スワイプで桁移動
                                // 通常: 左スワイプで次の桁(Next)、右スワイプで前の桁(Prev)
                                // 反転時: 右スワイプで次の桁(Next)、左スワイプで前の桁(Prev)
                                val goNext = if (!invertHorizontal) isLeft else isRight

                                if (appState == AppState.SETUP) {
                                    if (goNext) {
                                        // 次の桁へ
                                        if (activeDigitIndex < 3) {
                                            activeDigitIndex++
                                            playClickHaptic(false)
                                        } else {
                                            // 最後の桁で次へ ➔ 確定スタート
                                            val totalSec = (digits[0] * 10 + digits[1]) * 60L + (digits[2] * 10 + digits[3])
                                            if (totalSec > 0) {
                                                remainingSeconds = totalSec
                                                appState = AppState.RUNNING
                                                OngoingTimerHelper.showOngoingPill(context, totalSec)
                                                playClickHaptic(true)
                                            }
                                        }
                                    } else {
                                        // 前の桁へ
                                        if (activeDigitIndex > 0) {
                                            activeDigitIndex--
                                            playClickHaptic(false)
                                        }
                                    }
                                } else if (appState == AppState.RINGING) {
                                    appState = AppState.SETUP
                                    SoundAndVibeHelper.stopAlarmSoundAndVibe(context)
                                    playClickHaptic(false)
                                }
                            }
                        } else {
                            val isUp = totalDragY < -threshold
                            val isDown = totalDragY > threshold

                            if (isUp || isDown) {
                                // 上下スワイプ
                                // 通常: 上=確定(即スタート), 下=リセット
                                // 反転時: 下=確定(即スタート), 上=リセット
                                val isConfirm = if (!invertVertical) isUp else isDown

                                if (isConfirm) {
                                    // 確定操作 (上スワイプ)
                                    if (appState == AppState.SETUP) {
                                        val totalSec = (digits[0] * 10 + digits[1]) * 60L + (digits[2] * 10 + digits[3])
                                        if (totalSec > 0) {
                                            remainingSeconds = totalSec
                                            appState = AppState.RUNNING
                                            OngoingTimerHelper.showOngoingPill(context, totalSec)
                                            playClickHaptic(true)
                                        }
                                    }
                                } else {
                                    // リセット操作 (下スワイプ)
                                    if (appState == AppState.SETUP) {
                                        // 設定中は一発で全リセット 00:00
                                        digits = intArrayOf(0, 0, 0, 0)
                                        activeDigitIndex = 0
                                        OngoingTimerHelper.hideOngoingPill(context)
                                        playClickHaptic(true)
                                    } else if (appState == AppState.PAUSED) {
                                        // 一時停止中のリセット
                                        appState = AppState.SETUP
                                        activeDigitIndex = 0
                                        digits = intArrayOf(0, 0, 0, 0)
                                        OngoingTimerHelper.hideOngoingPill(context)
                                        playClickHaptic(true)
                                    }
                                }
                            }
                        }
                    }
                )
            }
            .pointerInput(appState, activeDigitIndex) {
                detectTapGestures(
                    onTap = { offset: Offset ->
                        if (appState == AppState.SETTINGS) return@detectTapGestures

                        val h = size.height
                        val isTopTwoThirds = offset.y < h * 0.67f

                        when (appState) {
                            AppState.SETUP -> {
                                val currentVal = digits[activeDigitIndex]
                                val maxLimit = when (activeDigitIndex) {
                                    0 -> 9 // 10 min
                                    1 -> 9 // 1 min
                                    2 -> 5 // 10 sec (0..5)
                                    3 -> 9 // 1 sec
                                    else -> 9
                                }
                                if (isTopTwoThirds) {
                                    // +1 Tap Area
                                    digits[activeDigitIndex] = if (currentVal >= maxLimit) 0 else currentVal + 1
                                } else {
                                    // -1 Tap Area
                                    digits[activeDigitIndex] = if (currentVal <= 0) maxLimit else currentVal - 1
                                }
                                digits = digits.clone()
                                playClickHaptic(false)
                            }
                            AppState.RUNNING -> {
                                appState = AppState.PAUSED
                                OngoingTimerHelper.hideOngoingPill(context)
                                playClickHaptic(false)
                            }
                            AppState.PAUSED -> {
                                appState = AppState.RUNNING
                                OngoingTimerHelper.showOngoingPill(context, remainingSeconds)
                                playClickHaptic(false)
                            }
                            AppState.RINGING -> {
                                appState = AppState.SETUP
                                SoundAndVibeHelper.stopAlarmSoundAndVibe(context)
                                OngoingTimerHelper.hideOngoingPill(context)
                                playClickHaptic(false)
                            }
                            AppState.SETTINGS -> {}
                        }
                    },
                    onLongPress = {
                        // 長押しで「設定画面」を開く
                        if (appState == AppState.SETUP || appState == AppState.PAUSED) {
                            appState = AppState.SETTINGS
                            playClickHaptic(true)
                        } else if (appState == AppState.SETTINGS) {
                            appState = AppState.SETUP
                            playClickHaptic(true)
                        }
                    }
                )
            }
    ) {
        if (appState == AppState.SETTINGS) {
            // 設定画面（上下・左右の操作入れ替え ＆ テーマ切り替え）
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(horizontal = 24.dp, vertical = 20.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center
            ) {
                Text(
                    text = "⚙️ 設定",
                    color = currentTheme.activeFg,
                    fontSize = 18.sp,
                    fontWeight = FontWeight.Bold
                )
                Spacer(modifier = Modifier.height(10.dp))

                // 左右スワイプ切り替えボタン
                val hLabel = if (!invertHorizontal) "左右: [左]次桁 / [右]前桁" else "左右: [右]次桁 / [左]前桁"
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(currentTheme.activeFg.copy(alpha = 0.15f), RoundedCornerShape(8.dp))
                        .clickable {
                            invertHorizontal = !invertHorizontal
                            saveSettings()
                            playClickHaptic(false)
                        }
                        .padding(vertical = 8.dp),
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        text = hLabel,
                        color = currentTheme.activeFg,
                        fontSize = 13.sp,
                        fontWeight = FontWeight.Medium,
                        textAlign = TextAlign.Center
                    )
                }

                Spacer(modifier = Modifier.height(8.dp))

                // 上下スワイプ切り替えボタン
                val vLabel = if (!invertVertical) "上下: [上]確定 / [下]リセット" else "上下: [下]確定 / [上]リセット"
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(currentTheme.activeFg.copy(alpha = 0.15f), RoundedCornerShape(8.dp))
                        .clickable {
                            invertVertical = !invertVertical
                            saveSettings()
                            playClickHaptic(false)
                        }
                        .padding(vertical = 8.dp),
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        text = vLabel,
                        color = currentTheme.activeFg,
                        fontSize = 13.sp,
                        fontWeight = FontWeight.Medium,
                        textAlign = TextAlign.Center
                    )
                }

                Spacer(modifier = Modifier.height(8.dp))

                // テーマ切り替え
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(currentTheme.activeFg.copy(alpha = 0.15f), RoundedCornerShape(8.dp))
                        .clickable {
                            currentThemeIndex = (currentThemeIndex + 1) % AppTheme.values().size
                            saveSettings()
                            playClickHaptic(false)
                        }
                        .padding(vertical = 8.dp),
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        text = "🎨 テーマ: ${currentTheme.title}",
                        color = currentTheme.activeFg,
                        fontSize = 13.sp,
                        fontWeight = FontWeight.Medium
                    )
                }

                Spacer(modifier = Modifier.height(8.dp))

                // 戻るボタン
                Text(
                    text = "長押し または タップで戻る",
                    color = currentTheme.inactiveFg,
                    fontSize = 11.sp,
                    modifier = Modifier.clickable {
                        appState = AppState.SETUP
                        playClickHaptic(false)
                    }
                )
            }
        } else {
            // 通常のタイマー画面
            // Subtle Hairline at 2/3 (Setup Mode only)
            if (appState == AppState.SETUP) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth(0.75f)
                        .height(1.dp)
                        .align(Alignment.TopCenter)
                        .padding(top = 295.dp)
                        .background(currentTheme.hairline)
                )
            }

            // Center Big Display
            Row(
                modifier = Modifier.align(Alignment.Center),
                verticalAlignment = Alignment.CenterVertically
            ) {
                if (appState == AppState.SETUP) {
                    // Digits with active highlighting
                    Text(
                        text = "${digits[0]}",
                        color = if (activeDigitIndex == 0) currentTheme.activeFg else currentTheme.inactiveFg,
                        fontSize = 58.sp,
                        fontWeight = FontWeight.Bold,
                        fontFamily = FontFamily.SansSerif
                    )
                    Text(
                        text = "${digits[1]}",
                        color = if (activeDigitIndex == 1) currentTheme.activeFg else currentTheme.inactiveFg,
                        fontSize = 58.sp,
                        fontWeight = FontWeight.Bold,
                        fontFamily = FontFamily.SansSerif
                    )
                    Text(
                        text = " : ",
                        color = currentTheme.inactiveFg,
                        fontSize = 52.sp,
                        fontWeight = FontWeight.Bold
                    )
                    Text(
                        text = "${digits[2]}",
                        color = if (activeDigitIndex == 2) currentTheme.activeFg else currentTheme.inactiveFg,
                        fontSize = 58.sp,
                        fontWeight = FontWeight.Bold,
                        fontFamily = FontFamily.SansSerif
                    )
                    Text(
                        text = "${digits[3]}",
                        color = if (activeDigitIndex == 3) currentTheme.activeFg else currentTheme.inactiveFg,
                        fontSize = 58.sp,
                        fontWeight = FontWeight.Bold,
                        fontFamily = FontFamily.SansSerif
                    )
                } else {
                    // Running / Paused / Ringing Mode
                    val m = (remainingSeconds / 60).toInt()
                    val s = (remainingSeconds % 60).toInt()
                    val mStr = String.format("%02d", m)
                    val sStr = String.format("%02d", s)

                    Text(
                        text = mStr,
                        color = if (appState == AppState.PAUSED) currentTheme.inactiveFg else currentTheme.activeFg,
                        fontSize = 58.sp,
                        fontWeight = FontWeight.Bold
                    )
                    Text(
                        text = " : ",
                        color = if (appState == AppState.RUNNING) {
                            currentTheme.activeFg.copy(alpha = colonAlpha)
                        } else {
                            currentTheme.activeFg
                        },
                        fontSize = 52.sp,
                        fontWeight = FontWeight.Bold
                    )
                    Text(
                        text = sStr,
                        color = if (appState == AppState.PAUSED) currentTheme.inactiveFg else currentTheme.activeFg,
                        fontSize = 58.sp,
                        fontWeight = FontWeight.Bold
                    )
                }
            }
        }
    }
}
