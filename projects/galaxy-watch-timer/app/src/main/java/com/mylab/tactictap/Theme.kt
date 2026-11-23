package com.mylab.tactictap

import androidx.compose.ui.graphics.Color

enum class AppTheme(
    val title: String,
    val isDark: Boolean,
    val bg: Color,
    val activeFg: Color,
    val inactiveFg: Color,
    val hairline: Color
) {
    DARK_AMBER(
        title = "Dark Amber",
        isDark = true,
        bg = Color(0xFF000000),
        activeFg = Color(0xFFFF8C00),
        inactiveFg = Color(0x73FF8C00), // ~45%
        hairline = Color(0x33FF8C00)
    ),
    DARK_GREEN(
        title = "Dark Green",
        isDark = true,
        bg = Color(0xFF000000),
        activeFg = Color(0xFF00FF6E),
        inactiveFg = Color(0x7300FF6E),
        hairline = Color(0x3300FF6E)
    ),
    DARK_MONO(
        title = "Dark Mono",
        isDark = true,
        bg = Color(0xFF000000),
        activeFg = Color(0xFFFFFFFF),
        inactiveFg = Color(0x73FFFFFF),
        hairline = Color(0x33FFFFFF)
    ),
    LIGHT_AMBER(
        title = "Light Amber",
        isDark = false,
        bg = Color(0xFFF8F8FA),
        activeFg = Color(0xFFE16400),
        inactiveFg = Color(0x73E16400),
        hairline = Color(0x33E16400)
    ),
    LIGHT_GREEN(
        title = "Light Green",
        isDark = false,
        bg = Color(0xFFF8F8FA),
        activeFg = Color(0xFF00A855),
        inactiveFg = Color(0x7300A855),
        hairline = Color(0x3300A855)
    ),
    LIGHT_MONO(
        title = "Light Mono",
        isDark = false,
        bg = Color(0xFFF8F8FA),
        activeFg = Color(0xFF14161A),
        inactiveFg = Color(0x7314161A),
        hairline = Color(0x3314161A)
    )
}
