package com.mylab.tactictap

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import kotlin.math.abs

/**
 * TacTicTap - Galaxy Watch 8 & Wear OS Native Entry Activity
 */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                TacTicTapApp()
            }
        }
    }
}

enum class AppState {
    SETUP, RUNNING, ALARM
}

// 6 Distinct Themes
enum class ColorTheme(
    val bg: Color,
    val activeFg: Color,
    val inactiveFg: Color,
    val hairline: Color
) {
    DARK_ORANGE(Color(0xFF000000), Color(0xFFFF8C00), Color(0x66FF8C00), Color(0x33FF8C00)),
    DARK_GREEN(Color(0xFF000000), Color(0xFF00FF6E), Color(0x6600FF6E), Color(0x3300FF6E)),
    DARK_MONO(Color(0xFF000000), Color(0xFFFFFFFF), Color(0x66FFFFFF), Color(0x33FFFFFF)),
    LIGHT_AMBER(Color(0xFFF7F7F9), Color(0xFFE16400), Color(0x66E16400), Color(0x40E16400)),
    LIGHT_GREEN(Color(0xFFF7F7F9), Color(0xFF00A855), Color(0x6600A855), Color(0x4000A855)),
    LIGHT_MONO(Color(0xFFF7F7F9), Color(0xFF1A1C20), Color(0x661A1C20), Color(0x331A1C20))
}

@Composable
fun TacTicTapApp() {
    var state by remember { mutableStateOf(AppState.SETUP) }
    var currentTheme by remember { mutableStateOf(ColorTheme.DARK_ORANGE) }

    // Digits: [M10, M1, S10, S1]
    var digits by remember { mutableStateOf(intArrayOf(0, 3, 0, 0)) }
    var activeCol by remember { mutableIntStateOf(1) } // Default to minute-1

    val limits = intArrayOf(5, 9, 5, 9)

    // Gesture Drag Accumulator
    var totalDragX by remember { mutableFloatStateOf(0f) }
    var totalDragY by remember { mutableFloatStateOf(0f) }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .clip(CircleShape)
            .background(currentTheme.bg)
            .pointerInput(state, activeCol) {
                detectTapGestures(
                    onTap = { offset ->
                        when (state) {
                            AppState.ALARM -> {
                                state = AppState.SETUP
                            }
                            AppState.RUNNING -> {
                                state = AppState.SETUP
                            }
                            AppState.SETUP -> {
                                val h = size.height
                                val currentVal = digits[activeCol]
                                val max = limits[activeCol]
                                val newDigits = digits.clone()

                                if (offset.y < h * 0.666f) {
                                    // Upper 2/3 Tap: +1
                                    newDigits[activeCol] = if (currentVal >= max) 0 else currentVal + 1
                                } else {
                                    // Lower 1/3 Tap: -1
                                    newDigits[activeCol] = if (currentVal <= 0) max else currentVal - 1
                                }
                                digits = newDigits
                            }
                        }
                    }
                )
            }
            .pointerInput(state, activeCol) {
                detectDragGestures(
                    onDragStart = {
                        totalDragX = 0f
                        totalDragY = 0f
                    },
                    onDragEnd = {
                        val threshold = 50f
                        if (abs(totalDragX) > abs(totalDragY)) {
                            // Horizontal Swipe -> Change Column
                            if (totalDragX < -threshold) {
                                activeCol = (activeCol + 1) % 4
                            } else if (totalDragX > threshold) {
                                activeCol = (activeCol - 1 + 4) % 4
                            }
                        } else {
                            // Vertical Swipe
                            if (totalDragY < -threshold) {
                                // Swipe Up -> Start Timer
                                state = AppState.RUNNING
                            } else if (totalDragY > threshold) {
                                // Swipe Down -> Reset
                                digits = intArrayOf(0, 0, 0, 0)
                            }
                        }
                    },
                    onDrag = { change, dragAmount ->
                        change.consume()
                        totalDragX += dragAmount.x
                        totalDragY += dragAmount.y
                    }
                )
            },
        contentAlignment = Alignment.Center
    ) {
        when (state) {
            AppState.SETUP -> {
                // Subtle dividing hairline at y = 66.6%
                Canvas(modifier = Modifier.fillMaxSize()) {
                    val y = size.height * 0.666f
                    drawLine(
                        color = currentTheme.hairline,
                        start = Offset(size.width * 0.15f, y),
                        end = Offset(size.width * 0.85f, y),
                        strokeWidth = 2f
                    )
                }

                // Digits Display (150pt scaled)
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.Center
                ) {
                    DigitText(digits[0].toString(), activeCol == 0, currentTheme)
                    DigitText(digits[1].toString(), activeCol == 1, currentTheme)
                    Text(
                        text = ":",
                        color = currentTheme.activeFg,
                        fontSize = 110.sp,
                        fontWeight = FontWeight.Bold
                    )
                    DigitText(digits[2].toString(), activeCol == 2, currentTheme)
                    DigitText(digits[3].toString(), activeCol == 3, currentTheme)
                }
            }
            AppState.RUNNING -> {
                Text(
                    text = "${digits[0]}${digits[1]}:${digits[2]}${digits[3]}",
                    color = currentTheme.activeFg,
                    fontSize = 115.sp,
                    fontWeight = FontWeight.Bold
                )
            }
            AppState.ALARM -> {
                Text(
                    text = "00:00",
                    color = currentTheme.activeFg,
                    fontSize = 120.sp,
                    fontWeight = FontWeight.Bold
                )
            }
        }
    }
}

@Composable
fun DigitText(char: String, isSelected: Boolean, theme: ColorTheme) {
    Text(
        text = char,
        color = if (isSelected) theme.activeFg else theme.inactiveFg,
        fontSize = 115.sp,
        fontWeight = FontWeight.Bold,
        modifier = Modifier.padding(horizontal = 1.dp)
    )
}
