package com.mylab.tactictap

import android.os.Bundle
import android.os.VibrationEffect
import android.os.Vibrator
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.wear.compose.material.Text
import kotlinx.coroutines.delay
import kotlin.math.abs

enum class AppState {
    SETUP,
    RUNNING,
    PAUSED,
    RINGING
}

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        // Check if launched as AlarmActivity alias
        val isAlarmMode = intent?.component?.className?.contains("AlarmActivity") == true
        
        setContent {
            TacTicTapApp(initialAlarmMode = isAlarmMode)
        }
    }
}

@Composable
fun TacTicTapApp(initialAlarmMode: Boolean) {
    val context = LocalContext.current
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

    var currentThemeIndex by remember { mutableIntStateOf(0) }
    val currentTheme = AppTheme.values()[currentThemeIndex]
    
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
                playClickHaptic(isDouble = true)
            }
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(currentTheme.bg)
            .pointerInput(appState, activeDigitIndex) {
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
                        val threshold = 40f
                        val isHorizontal = abs(totalDragX) > abs(totalDragY)

                        if (isHorizontal) {
                            if (totalDragX < -threshold) {
                                // Left Swipe: Next digit or Ringing Dismiss
                                if (appState == AppState.SETUP) {
                                    if (activeDigitIndex < 3) {
                                        activeDigitIndex++
                                        playClickHaptic(false)
                                    } else {
                                        // 4th digit left swipe: Start
                                        val totalSec = (digits[0] * 10 + digits[1]) * 60L + (digits[2] * 10 + digits[3])
                                        if (totalSec > 0) {
                                            remainingSeconds = totalSec
                                            appState = AppState.RUNNING
                                            playClickHaptic(true)
                                        }
                                    }
                                } else if (appState == AppState.RINGING) {
                                    appState = AppState.SETUP
                                    playClickHaptic(false)
                                }
                            }
                        } else {
                            if (totalDragY < -threshold) {
                                // Up Swipe: Quick start with remaining digits as 00
                                if (appState == AppState.SETUP) {
                                    val totalSec = (digits[0] * 10 + digits[1]) * 60L + (digits[2] * 10 + digits[3])
                                    if (totalSec > 0) {
                                        remainingSeconds = totalSec
                                        appState = AppState.RUNNING
                                        playClickHaptic(true)
                                    }
                                }
                            } else if (totalDragY > threshold) {
                                // Down Swipe: Undo / Reset
                                if (appState == AppState.SETUP) {
                                    if (activeDigitIndex > 0) {
                                        activeDigitIndex--
                                        playClickHaptic(false)
                                    } else {
                                        // Reset to 00:00
                                        digits = intArrayOf(0, 0, 0, 0)
                                        playClickHaptic(true)
                                    }
                                } else if (appState == AppState.PAUSED) {
                                    // Reset to setup
                                    appState = AppState.SETUP
                                    activeDigitIndex = 0
                                    playClickHaptic(true)
                                }
                            }
                        }
                    }
                )
            }
            .pointerInput(appState, activeDigitIndex) {
                detectTapGestures(
                    onTap = { offset: Offset ->
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
                                playClickHaptic(false)
                            }
                            AppState.PAUSED -> {
                                appState = AppState.RUNNING
                                playClickHaptic(false)
                            }
                            AppState.RINGING -> {
                                appState = AppState.SETUP
                                playClickHaptic(false)
                            }
                        }
                    },
                    onLongPress = {
                        // Long press cycles color themes cleanly
                        currentThemeIndex = (currentThemeIndex + 1) % AppTheme.values().size
                        playClickHaptic(true)
                    }
                )
            }
    ) {
        // Subtle Hairline at 2/3 (Setup Mode only)
        if (appState == AppState.SETUP) {
            Box(
                modifier = Modifier
                    .fillMaxWidth(0.75f)
                    .height(1.dp)
                    .align(Alignment.TopCenter)
                    .padding(top = 295.dp) // ~0.67 of 440dp screen
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
