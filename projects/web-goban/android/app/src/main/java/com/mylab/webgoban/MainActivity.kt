package com.mylab.webgoban

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.view.View
import android.view.WindowManager
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity

class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // フルスクリーン・常時点灯の初期設定
        window.decorView.systemUiVisibility = (
            View.SYSTEM_UI_FLAG_LAYOUT_STABLE
            or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
            or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
        )

        webView = WebView(this)
        setContentView(webView)

        setupWebView()
        setupBackHandler()

        // サーバーURL読み込み
        val targetUrl = intent.getStringExtra("SERVER_URL") ?: BuildConfig.DEFAULT_SERVER_URL
        webView.loadUrl(targetUrl)

        // 共有インテント（SGFやテキスト）の処理
        handleIncomingIntent(intent)
    }

    private fun setupWebView() {
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            useWideViewPort = true
            loadWithOverviewMode = true
            mediaPlaybackRequiresUserGesture = false
            cacheMode = WebSettings.LOAD_DEFAULT
            mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
        }

        webView.webChromeClient = WebChromeClient()
        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                return false
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                // ページ読み込み完了時に安全領域（インセット）CSS変数を注入
                injectSafeAreaInsets()
            }
        }

        // PlatformBridge 連携用ネイティブインターフェース登録
        webView.addJavascriptInterface(WebGobanNativeInterface(this, webView), "WebGobanNative")
    }

    private fun setupBackHandler() {
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                // フロントエンド（PlatformBridge / window.WebGobanApp）に「戻る」イベントを委譲
                webView.evaluateJavascript(
                    "window.WebGobanApp && typeof window.WebGobanApp.handleHardwareBack === 'function' ? window.WebGobanApp.handleHardwareBack() : false"
                ) { result ->
                    val consumed = result == "true"
                    if (!consumed) {
                        // フロント側で戻る処理がなければ、ブラウザ履歴またはアプリ終了
                        if (webView.canGoBack()) {
                            webView.goBack()
                        } else {
                            isEnabled = false
                            onBackPressedDispatcher.onBackPressed()
                        }
                    }
                }
            }
        })
    }

    private fun injectSafeAreaInsets() {
        val script = """
            (() => {
                const root = document.documentElement;
                root.style.setProperty('--app-inset-top', '24px');
                root.style.setProperty('--app-inset-bottom', '16px');
                root.style.setProperty('--app-inset-left', '0px');
                root.style.setProperty('--app-inset-right', '0px');
            })();
        """.trimIndent()
        webView.evaluateJavascript(script, null)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIncomingIntent(intent)
    }

    private fun handleIncomingIntent(intent: Intent?) {
        if (intent == null) return
        val action = intent.action
        val type = intent.type

        var payloadText: String? = null
        if (Intent.ACTION_SEND == action && type != null) {
            payloadText = intent.getStringExtra(Intent.EXTRA_TEXT)
        } else if (Intent.ACTION_VIEW == action) {
            val dataUri = intent.data
            if (dataUri != null) {
                try {
                    contentResolver.openInputStream(dataUri)?.use { stream ->
                        payloadText = stream.bufferedReader().readText()
                    }
                } catch (e: Exception) {
                    // ignore
                }
            }
        }

        if (!payloadText.isNullOrBlank()) {
            val escaped = payloadText!!.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "")
            webView.evaluateJavascript(
                "window.WebGobanApp && typeof window.WebGobanApp.receivePayload === 'function' ? window.WebGobanApp.receivePayload('$escaped') : false",
                null
            )
        }
    }
}

/**
 * JS (PlatformBridge) から呼び出されるネイティブ機能の実装
 */
class WebGobanNativeInterface(private val activity: Activity, private val webView: WebView) {

    private val vibrator: Vibrator? by lazy {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            val manager = activity.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as? VibratorManager
            manager?.defaultVibrator
        } else {
            @Suppress("DEPRECATION")
            activity.getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
        }
    }

    @JavascriptInterface
    fun haptic(kind: String) {
        val vib = vibrator ?: return
        if (!vib.hasVibrator()) return

        val duration = when (kind) {
            "tick" -> 8L
            "place" -> 16L
            "confirm" -> 22L
            "error" -> 36L
            else -> 12L
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            vib.vibrate(VibrationEffect.createOneShot(duration, VibrationEffect.DEFAULT_AMPLITUDE))
        } else {
            @Suppress("DEPRECATION")
            vib.vibrate(duration)
        }
    }

    @JavascriptInterface
    fun setKeepScreenOn(enabled: Boolean) {
        activity.runOnUiThread {
            if (enabled) {
                activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            } else {
                activity.window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            }
        }
    }

    @JavascriptInterface
    fun copyText(text: String) {
        activity.runOnUiThread {
            val clipboard = activity.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
            val clip = ClipData.newPlainText("WebGoban", text)
            clipboard?.setPrimaryClip(clip)
            Toast.makeText(activity, "クリップボードにコピーしました", Toast.LENGTH_SHORT).show()
        }
    }

    @JavascriptInterface
    fun shareFile(filename: String, content: String, mimeType: String) {
        activity.runOnUiThread {
            val sendIntent = Intent().apply {
                action = Intent.ACTION_SEND
                putExtra(Intent.EXTRA_TEXT, content)
                type = "text/plain"
            }
            val shareIntent = Intent.createChooser(sendIntent, filename)
            activity.startActivity(shareIntent)
        }
    }

    @JavascriptInterface
    fun setSystemBarTheme(hex: String, darkIcons: Boolean) {
        // 必要に応じてステータスバー色変更
    }

    @JavascriptInterface
    fun updateBoardExclusionZone(rectJson: String) {
        // S26 Ultra 画面端での Android 戻るジェスチャー除外領域の設定（API 29+）
    }
}
