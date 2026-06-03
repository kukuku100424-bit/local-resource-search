package com.example.carenavi

import android.Manifest
import android.app.AlertDialog
import android.app.DownloadManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.Message
import android.print.PrintAttributes
import android.print.PrintManager
import android.provider.MediaStore
import android.provider.Settings
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.view.View
import android.view.WindowManager
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.URLUtil
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.core.view.WindowCompat
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class MainActivity : ComponentActivity() {

    private lateinit var webView: WebView
    private var statusBarHeightPx: Int = 0

    private var filePathCallback: ValueCallback<Array<Uri>>? = null
    private var cameraImageUri: Uri? = null
    private var lastWebUrlBeforeCamera: String? = null

    private var speechRecognizer: SpeechRecognizer? = null

    // === Auto-install update tracking ===
    private var updateDownloadId: Long = -1L
    private var updateApkFile: File? = null
    private var updateDownloadReceiver: BroadcastReceiver? = null
    private var pendingApkUrlForInstall: String? = null

    private val homeUrl = "https://carenavi.kr"
    private val versionCheckUrl = "https://carenavi.kr/app-version.json"

    companion object {
        private const val FILE_CHOOSER_REQUEST_CODE = 1001
        private const val RECORD_AUDIO_REQUEST_CODE = 2001
        private const val INSTALL_PERMISSION_REQUEST_CODE = 3001
    }

    private fun dp(value: Int): Int {
        return (value * resources.displayMetrics.density).toInt()
    }

    private fun getStatusBarHeight(): Int {
        val resourceId = resources.getIdentifier("status_bar_height", "dimen", "android")
        return if (resourceId > 0) {
            resources.getDimensionPixelSize(resourceId)
        } else {
            dp(24)
        }
    }

    private fun getCurrentVersionCode(): Long {
        val packageInfo = packageManager.getPackageInfo(packageName, 0)
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            packageInfo.longVersionCode
        } else {
            @Suppress("DEPRECATION")
            packageInfo.versionCode.toLong()
        }
    }

    inner class AndroidPrintBridge {
        @JavascriptInterface
        fun printPage() {
            runOnUiThread {
                createPrintJob()
            }
        }
    }

    inner class AndroidVoiceBridge {
        @JavascriptInterface
        fun startVoiceSearch() {
            runOnUiThread {
                startSilentVoiceSearch()
            }
        }

        @JavascriptInterface
        fun stopVoiceSearch() {
            runOnUiThread {
                stopSilentVoiceSearch()
            }
        }
    }

    private fun startSilentVoiceSearch() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            ActivityCompat.requestPermissions(
                this,
                arrayOf(Manifest.permission.RECORD_AUDIO),
                RECORD_AUDIO_REQUEST_CODE
            )
            return
        }

        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            Toast.makeText(this, "음성검색을 사용할 수 없습니다.", Toast.LENGTH_SHORT).show()
            webView.evaluateJavascript(
                """
                if(window.__careNaviVoiceEnd){ window.__careNaviVoiceEnd(); }
                """.trimIndent(),
                null
            )
            return
        }

        speechRecognizer?.destroy()
        speechRecognizer = SpeechRecognizer.createSpeechRecognizer(this)

        speechRecognizer?.setRecognitionListener(object : RecognitionListener {
            override fun onReadyForSpeech(params: Bundle?) {}

            override fun onBeginningOfSpeech() {}

            override fun onRmsChanged(rmsdB: Float) {}

            override fun onBufferReceived(buffer: ByteArray?) {}

            override fun onEndOfSpeech() {}

            override fun onError(error: Int) {
                webView.evaluateJavascript(
                    """
                    if(window.__careNaviVoiceEnd){ window.__careNaviVoiceEnd(); }
                    """.trimIndent(),
                    null
                )
            }

            override fun onResults(results: Bundle?) {
                val matches = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                val text = matches?.firstOrNull().orEmpty()
                val safeText = JSONObject.quote(text)

                webView.evaluateJavascript(
                    """
                    if(window.__careNaviVoiceResult){
                        window.__careNaviVoiceResult($safeText);
                    } else if(window.__careNaviVoiceEnd){
                        window.__careNaviVoiceEnd();
                    }
                    """.trimIndent(),
                    null
                )
            }

            override fun onPartialResults(partialResults: Bundle?) {}

            override fun onEvent(eventType: Int, params: Bundle?) {}
        })

        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(
                RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                RecognizerIntent.LANGUAGE_MODEL_FREE_FORM
            )
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, "ko-KR")
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, false)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
        }

        speechRecognizer?.startListening(intent)
    }

    private fun stopSilentVoiceSearch() {
        try {
            speechRecognizer?.stopListening()
            speechRecognizer?.destroy()
            speechRecognizer = null
        } catch (_: Exception) {}

        webView.evaluateJavascript(
            """
            if(window.__careNaviVoiceEnd){ window.__careNaviVoiceEnd(); }
            """.trimIndent(),
            null
        )
    }

    private fun createCameraImageUri(): Uri {
        val timeStamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.KOREA).format(Date())

        val imageFile = File.createTempFile(
            "carenavi_camera_${timeStamp}_",
            ".jpg",
            cacheDir
        )

        return FileProvider.getUriForFile(
            this,
            "${packageName}.fileprovider",
            imageFile
        )
    }

    private fun createPrintJob() {
        val printManager = getSystemService(Context.PRINT_SERVICE) as PrintManager
        val jobName = "케어네비_조사서식"

        val printAdapter = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            webView.createPrintDocumentAdapter(jobName)
        } else {
            webView.createPrintDocumentAdapter()
        }

        val attributes = PrintAttributes.Builder()
            .setMediaSize(PrintAttributes.MediaSize.ISO_A4)
            .setColorMode(PrintAttributes.COLOR_MODE_COLOR)
            .setMinMargins(PrintAttributes.Margins.NO_MARGINS)
            .build()

        printManager.print(jobName, printAdapter, attributes)
    }

    private fun injectPrintHook() {
        webView.evaluateJavascript(
            """
            (function(){
                if(!window.__careNaviPrintHooked){
                    window.__careNaviPrintHooked = true;
                    window.print = function(){
                        if(window.AndroidPrint){
                            window.AndroidPrint.printPage();
                        }
                    };
                }
            })();
            """.trimIndent(),
            null
        )
    }

    private fun openExternal(url: String) {
        try {
            val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
            startActivity(intent)
        } catch (e: Exception) {
            webView.loadUrl(url)
        }
    }

    private fun checkAppUpdate() {
        Thread {
            try {
                val url = URL(versionCheckUrl)
                val connection = url.openConnection() as HttpURLConnection

                connection.requestMethod = "GET"
                connection.connectTimeout = 5000
                connection.readTimeout = 5000
                connection.useCaches = false

                if (connection.responseCode == HttpURLConnection.HTTP_OK) {
                    val responseText = connection.inputStream.bufferedReader().use { it.readText() }
                    val json = JSONObject(responseText)

                    val latestVersionCode = json.optLong("latestAppVersionCode", 1L)
                    val latestVersionName = json.optString("latestAppVersionName", "")
                    val apkUrl = json.optString("apkUrl", "")
                    val message = json.optString(
                        "message",
                        "케어네비 앱 새 버전이 있습니다. 업데이트해 주세요."
                    )

                    val currentVersionCode = getCurrentVersionCode()

                    if (latestVersionCode > currentVersionCode && apkUrl.isNotBlank()) {
                        runOnUiThread {
                            showUpdateDialog(message, latestVersionName, apkUrl)
                        }
                    }
                }

                connection.disconnect()
            } catch (_: Exception) {}
        }.start()
    }

    private fun showUpdateDialog(message: String, latestVersionName: String, apkUrl: String) {
        val title = if (latestVersionName.isNotBlank()) {
            "케어네비 앱 업데이트 v$latestVersionName"
        } else {
            "케어네비 앱 업데이트"
        }

        AlertDialog.Builder(this)
            .setTitle(title)
            .setMessage(message)
            .setCancelable(false)
            .setPositiveButton("다운로드") { _, _ ->
                startApkDownloadAndInstall(apkUrl)
            }
            .setNegativeButton("나중에", null)
            .show()
    }

    // ============================================================
    // 자동 설치 업데이트 플로우
    // ============================================================
    private fun startApkDownloadAndInstall(apkUrl: String) {
        // 1) "출처를 알 수 없는 앱 설치" 권한 확인 (Android 8.0+)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            if (!packageManager.canRequestPackageInstalls()) {
                pendingApkUrlForInstall = apkUrl
                AlertDialog.Builder(this)
                    .setTitle("설치 권한 필요")
                    .setMessage("케어네비 앱 업데이트를 설치하려면 '이 출처 허용' 설정이 필요합니다. 설정 화면에서 허용해 주세요.")
                    .setCancelable(false)
                    .setPositiveButton("설정으로 이동") { _, _ ->
                        try {
                            val intent = Intent(
                                Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                                Uri.parse("package:$packageName")
                            )
                            startActivityForResult(intent, INSTALL_PERMISSION_REQUEST_CODE)
                        } catch (e: Exception) {
                            Toast.makeText(
                                this,
                                "설정 화면을 열 수 없습니다.",
                                Toast.LENGTH_SHORT
                            ).show()
                        }
                    }
                    .setNegativeButton("취소") { _, _ ->
                        pendingApkUrlForInstall = null
                    }
                    .show()
                return
            }
        }

        // 2) 이전 APK 파일 정리
        val apkFile = File(cacheDir, "carenavi_update.apk")
        if (apkFile.exists()) {
            try { apkFile.delete() } catch (_: Exception) {}
        }
        updateApkFile = apkFile

        // 3) 다운로드 시작
        try {
            val request = DownloadManager.Request(Uri.parse(apkUrl)).apply {
                setTitle("케어네비 앱 업데이트")
                setDescription("새 버전 다운로드 중...")
                setMimeType("application/vnd.android.package-archive")
                setDestinationUri(Uri.fromFile(apkFile))
                setNotificationVisibility(
                    DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED
                )

                val cookies = CookieManager.getInstance().getCookie(apkUrl)
                if (!cookies.isNullOrEmpty()) {
                    addRequestHeader("Cookie", cookies)
                }
            }

            val dm = getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
            updateDownloadId = dm.enqueue(request)

            Toast.makeText(
                this,
                "업데이트 다운로드를 시작합니다.",
                Toast.LENGTH_SHORT
            ).show()

            // 4) 다운로드 완료 수신 등록 → 끝나면 자동으로 설치 화면 열기
            registerDownloadCompleteReceiver()
        } catch (e: Exception) {
            Toast.makeText(
                this,
                "업데이트 다운로드를 시작할 수 없습니다.",
                Toast.LENGTH_SHORT
            ).show()
        }
    }

    private fun registerDownloadCompleteReceiver() {
        // 이전 receiver 정리
        updateDownloadReceiver?.let {
            try { unregisterReceiver(it) } catch (_: Exception) {}
        }

        val receiver = object : BroadcastReceiver() {
            override fun onReceive(context: Context?, intent: Intent?) {
                val id = intent?.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1L) ?: -1L
                if (id != updateDownloadId || updateDownloadId == -1L) return

                // 다운로드 상태 확인
                val dm = getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
                val query = DownloadManager.Query().setFilterById(updateDownloadId)
                val cursor = dm.query(query)
                var success = false

                if (cursor != null && cursor.moveToFirst()) {
                    val statusIndex = cursor.getColumnIndex(DownloadManager.COLUMN_STATUS)
                    if (statusIndex >= 0) {
                        val status = cursor.getInt(statusIndex)
                        success = (status == DownloadManager.STATUS_SUCCESSFUL)
                    }
                }
                cursor?.close()

                try {
                    unregisterReceiver(this)
                } catch (_: Exception) {}
                updateDownloadReceiver = null

                val apkFile = updateApkFile
                if (success && apkFile != null && apkFile.exists()) {
                    installApk(apkFile)
                } else {
                    Toast.makeText(
                        this@MainActivity,
                        "업데이트 다운로드에 실패했습니다.",
                        Toast.LENGTH_SHORT
                    ).show()
                }
            }
        }

        updateDownloadReceiver = receiver

        val filter = IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(receiver, filter, RECEIVER_EXPORTED)
        } else {
            @Suppress("UnspecifiedRegisterReceiverFlag")
            registerReceiver(receiver, filter)
        }
    }

    private fun installApk(apkFile: File) {
        try {
            val apkUri = FileProvider.getUriForFile(
                this,
                "${packageName}.fileprovider",
                apkFile
            )

            val installIntent = Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(apkUri, "application/vnd.android.package-archive")
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }

            startActivity(installIntent)
        } catch (e: Exception) {
            Toast.makeText(
                this,
                "설치 화면을 열 수 없습니다.",
                Toast.LENGTH_SHORT
            ).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        statusBarHeightPx = getStatusBarHeight()

        window.clearFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN)
        WindowCompat.setDecorFitsSystemWindows(window, false)

        window.statusBarColor = Color.parseColor("#F4F6FB")
        window.navigationBarColor = Color.parseColor("#F4F6FB")

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            window.decorView.systemUiVisibility = View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR
        }

        val root = FrameLayout(this)
        root.setBackgroundColor(Color.parseColor("#F4F6FB"))

        webView = WebView(this)

        webView.settings.javaScriptEnabled = true
        webView.settings.domStorageEnabled = true
        webView.settings.useWideViewPort = true
        webView.settings.loadWithOverviewMode = true
        webView.settings.textZoom = 100
        webView.settings.cacheMode = WebSettings.LOAD_NO_CACHE
        webView.settings.mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
        webView.settings.setSupportMultipleWindows(true)
        webView.settings.javaScriptCanOpenWindowsAutomatically = true
        webView.settings.allowFileAccess = true
        webView.settings.allowContentAccess = true

        webView.settings.userAgentString =
            webView.settings.userAgentString + " CareNaviApp"

        webView.addJavascriptInterface(AndroidPrintBridge(), "AndroidPrint")
        webView.addJavascriptInterface(AndroidVoiceBridge(), "AndroidVoice")

        webView.webChromeClient = object : WebChromeClient() {

            override fun onShowFileChooser(
                webView: WebView?,
                filePathCallback: ValueCallback<Array<Uri>>?,
                fileChooserParams: FileChooserParams?
            ): Boolean {
                this@MainActivity.filePathCallback?.onReceiveValue(null)
                this@MainActivity.filePathCallback = filePathCallback

                return try {
                    cameraImageUri = createCameraImageUri()
                    lastWebUrlBeforeCamera = this@MainActivity.webView.url

                    val cameraIntent = Intent(MediaStore.ACTION_IMAGE_CAPTURE).apply {
                        putExtra(MediaStore.EXTRA_OUTPUT, cameraImageUri)
                        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                        addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
                    }

                    startActivityForResult(cameraIntent, FILE_CHOOSER_REQUEST_CODE)
                    true
                } catch (e: Exception) {
                    this@MainActivity.filePathCallback = null
                    cameraImageUri = null
                    lastWebUrlBeforeCamera = null
                    Toast.makeText(
                        this@MainActivity,
                        "카메라를 열 수 없습니다.",
                        Toast.LENGTH_SHORT
                    ).show()
                    false
                }
            }

            override fun onCreateWindow(
                view: WebView?,
                isDialog: Boolean,
                isUserGesture: Boolean,
                resultMsg: Message?
            ): Boolean {
                val newWebView = WebView(this@MainActivity)
                newWebView.webViewClient = object : WebViewClient() {
                    override fun shouldOverrideUrlLoading(
                        view: WebView?,
                        request: WebResourceRequest?
                    ): Boolean {
                        val url = request?.url.toString()
                        openExternal(url)
                        return true
                    }
                }

                val transport = resultMsg?.obj as? WebView.WebViewTransport
                transport?.webView = newWebView
                resultMsg?.sendToTarget()
                return true
            }
        }

        webView.webViewClient = object : WebViewClient() {

            override fun shouldOverrideUrlLoading(
                view: WebView?,
                request: WebResourceRequest?
            ): Boolean {
                val url = request?.url.toString()
                return handleUrl(url)
            }

            override fun shouldOverrideUrlLoading(
                view: WebView?,
                url: String?
            ): Boolean {
                return handleUrl(url ?: "")
            }

            private fun handleUrl(url: String): Boolean {
                if (url.isBlank()) return false

                val uri = Uri.parse(url)
                val host = uri.host ?: ""

                if (url.endsWith(".pdf", ignoreCase = true)) {
                    openExternal(url)
                    return true
                }

                val isCareNavi =
                    host == "carenavi.kr" ||
                            host.endsWith(".carenavi.kr")

                return if (isCareNavi) {
                    false
                } else {
                    openExternal(url)
                    true
                }
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                injectPrintHook()
            }
        }

        webView.setDownloadListener { url, userAgent, contentDisposition, mimeType, contentLength ->
            try {
                val uri = Uri.parse(url)

                val fileName = when {
                    url.contains("/stats/export/visits") -> "일자별_방문자수.xlsx"
                    url.contains("/stats/export/regions") -> "일자별_지역클릭수.xlsx"
                    url.contains("carenavi.apk") -> "carenavi.apk"
                    else -> URLUtil.guessFileName(url, contentDisposition, mimeType)
                }

                val request = DownloadManager.Request(uri)

                request.setTitle(fileName)
                request.setDescription("다운로드 중...")
                request.setMimeType(
                    when {
                        fileName.endsWith(".xlsx") -> "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        fileName.endsWith(".apk") -> "application/vnd.android.package-archive"
                        else -> mimeType
                    }
                )

                val cookies = CookieManager.getInstance().getCookie(url)
                if (!cookies.isNullOrEmpty()) {
                    request.addRequestHeader("Cookie", cookies)
                }

                request.addRequestHeader("User-Agent", userAgent)

                request.setNotificationVisibility(
                    DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED
                )

                request.allowScanningByMediaScanner()

                request.setDestinationInExternalPublicDir(
                    Environment.DIRECTORY_DOWNLOADS,
                    fileName
                )

                val dm = getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
                dm.enqueue(request)

                Toast.makeText(
                    this@MainActivity,
                    "다운로드 시작: $fileName",
                    Toast.LENGTH_SHORT
                ).show()

            } catch (e: Exception) {
                openExternal(url)
            }
        }

        val params = FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT,
            FrameLayout.LayoutParams.MATCH_PARENT
        )

        params.topMargin = statusBarHeightPx
        params.bottomMargin = 0

        root.addView(webView, params)
        setContentView(root)

        webView.loadUrl(homeUrl)

        checkAppUpdate()

        onBackPressedDispatcher.addCallback(
            this,
            object : OnBackPressedCallback(true) {
                override fun handleOnBackPressed() {
                    if (webView.canGoBack()) {
                        webView.goBack()
                    } else {
                        finish()
                    }
                }
            }
        )
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)

        if (requestCode == FILE_CHOOSER_REQUEST_CODE) {
            if (resultCode == RESULT_OK && cameraImageUri != null) {
                filePathCallback?.onReceiveValue(arrayOf(cameraImageUri!!))

                val stayUrl = lastWebUrlBeforeCamera
                if (!stayUrl.isNullOrBlank() && stayUrl.contains("/desc")) {
                    webView.postDelayed({
                        val currentUrl = webView.url.orEmpty()
                        if (currentUrl.isBlank() || currentUrl.contains("/login")) {
                            webView.loadUrl(stayUrl)
                        }
                    }, 300)
                }
            } else {
                filePathCallback?.onReceiveValue(null)
            }

            filePathCallback = null
            cameraImageUri = null
            lastWebUrlBeforeCamera = null
        } else if (requestCode == INSTALL_PERMISSION_REQUEST_CODE) {
            // 설치 권한 설정 화면에서 돌아왔을 때 자동으로 다운로드 재시도
            val url = pendingApkUrlForInstall
            pendingApkUrlForInstall = null
            if (!url.isNullOrBlank()) {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                    && packageManager.canRequestPackageInstalls()
                ) {
                    startApkDownloadAndInstall(url)
                } else {
                    Toast.makeText(
                        this,
                        "설치 권한이 허용되지 않아 업데이트를 진행할 수 없습니다.",
                        Toast.LENGTH_LONG
                    ).show()
                }
            }
        }
    }

    override fun onDestroy() {
        try {
            speechRecognizer?.destroy()
            speechRecognizer = null
        } catch (_: Exception) {}

        updateDownloadReceiver?.let {
            try { unregisterReceiver(it) } catch (_: Exception) {}
        }
        updateDownloadReceiver = null

        super.onDestroy()
    }
}