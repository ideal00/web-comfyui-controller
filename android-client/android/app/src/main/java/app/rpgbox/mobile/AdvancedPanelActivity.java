package app.rpgbox.mobile;

import android.Manifest;
import android.app.Activity;
import android.app.DownloadManager;
import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.DownloadListener;
import android.webkit.JavascriptInterface;
import android.webkit.SslErrorHandler;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.net.http.SslError;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;

/** Native container for the computer's full Easy Panel web UI. */
@SuppressWarnings("deprecation")
public class AdvancedPanelActivity extends Activity {

    public static final String EXTRA_URL = "easy_panel_url";
    private static final int FILE_CHOOSER_REQUEST = 4101;
    private static final int DOWNLOAD_PERMISSION_REQUEST = 4102;

    private WebView webView;
    private ProgressBar progressBar;
    private View errorView;
    private TextView errorMessage;
    private TextView titleView;
    private String panelUrl;
    private String panelScheme;
    private String panelHost;
    private int panelPort;
    private ValueCallback<Uri[]> fileChooserCallback;
    private DownloadSpec pendingDownload;
    private JsDownloadSpec pendingJsDownload;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(Color.rgb(11, 18, 21));
        getWindow().setNavigationBarColor(Color.rgb(11, 18, 21));

        panelUrl = getIntent().getStringExtra(EXTRA_URL);
        if (!isSafePanelUrl(panelUrl)) {
            Toast.makeText(this, "高级面板地址无效", Toast.LENGTH_LONG).show();
            finish();
            return;
        }
        Uri parsed = Uri.parse(panelUrl);
        panelScheme = parsed.getScheme();
        panelHost = parsed.getHost();
        panelPort = parsed.getPort() == -1 ? defaultPort(panelScheme) : parsed.getPort();

        buildLayout();
        configureWebView();
        if (savedInstanceState != null && webView.restoreState(savedInstanceState) != null) {
            return;
        }
        webView.loadUrl(panelUrl);
    }

    static boolean isSafePanelUrl(String rawUrl) {
        if (rawUrl == null || rawUrl.trim().isEmpty()) return false;
        Uri uri;
        try {
            uri = Uri.parse(rawUrl.trim());
        } catch (Exception ignored) {
            return false;
        }
        String scheme = uri.getScheme();
        String host = uri.getHost();
        String path = uri.getPath();
        String query = uri.getQuery();
        return ("http".equalsIgnoreCase(scheme) || "https".equalsIgnoreCase(scheme))
            && host != null && !host.trim().isEmpty()
            && uri.getUserInfo() == null
            && uri.getFragment() == null
            && (path == null || path.isEmpty() || "/".equals(path))
            && (query == null || query.isEmpty() || "mobile=1".equals(query));
    }

    private static int defaultPort(String scheme) {
        return "https".equalsIgnoreCase(scheme) ? 443 : 80;
    }

    private void buildLayout() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.rgb(11, 18, 21));
        root.setFitsSystemWindows(true);

        LinearLayout toolbar = new LinearLayout(this);
        toolbar.setGravity(Gravity.CENTER_VERTICAL);
        toolbar.setPadding(dp(8), 0, dp(6), 0);
        toolbar.setBackgroundColor(Color.rgb(14, 24, 29));
        root.addView(toolbar, new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, dp(54)));

        Button back = toolbarButton("‹ 返回");
        back.setContentDescription("返回快速生图");
        back.setOnClickListener(view -> goBackOrFinish());
        toolbar.addView(back, new LinearLayout.LayoutParams(dp(76), ViewGroup.LayoutParams.MATCH_PARENT));

        titleView = new TextView(this);
        titleView.setText("高级面板");
        titleView.setTextColor(Color.rgb(232, 244, 240));
        titleView.setTextSize(16);
        titleView.setGravity(Gravity.CENTER_VERTICAL);
        titleView.setSingleLine(true);
        toolbar.addView(titleView, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1));

        Button refresh = toolbarButton("↻");
        refresh.setContentDescription("刷新高级面板");
        refresh.setOnClickListener(view -> webView.reload());
        toolbar.addView(refresh, new LinearLayout.LayoutParams(dp(52), ViewGroup.LayoutParams.MATCH_PARENT));

        progressBar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progressBar.setMax(100);
        progressBar.setProgress(0);
        progressBar.setIndeterminate(false);
        progressBar.setVisibility(View.VISIBLE);
        root.addView(progressBar, new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, dp(3)));

        FrameLayout content = new FrameLayout(this);
        root.addView(content, new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));

        webView = new WebView(this);
        webView.setBackgroundColor(Color.rgb(11, 18, 21));
        content.addView(webView, new FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        errorView = createErrorView();
        FrameLayout.LayoutParams errorParams = new FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT);
        errorParams.gravity = Gravity.CENTER;
        content.addView(errorView, errorParams);
        errorView.setVisibility(View.GONE);

        setContentView(root);
    }

    private View createErrorView() {
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setGravity(Gravity.CENTER);
        panel.setPadding(dp(28), dp(28), dp(28), dp(28));
        panel.setBackgroundColor(Color.rgb(11, 18, 21));

        TextView heading = new TextView(this);
        heading.setText("高级面板暂时无法打开");
        heading.setTextColor(Color.rgb(235, 244, 241));
        heading.setTextSize(19);
        heading.setGravity(Gravity.CENTER);
        panel.addView(heading, new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        errorMessage = new TextView(this);
        errorMessage.setText("请确认电脑端 Easy Panel 正在运行，并检查手机与电脑的网络连接。");
        errorMessage.setTextColor(Color.rgb(159, 181, 174));
        errorMessage.setTextSize(13);
        errorMessage.setGravity(Gravity.CENTER);
        errorMessage.setPadding(0, dp(12), 0, dp(18));
        panel.addView(errorMessage, new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        Button retry = toolbarButton("重新加载");
        retry.setContentDescription("重新加载高级面板");
        retry.setOnClickListener(view -> webView.reload());
        LinearLayout.LayoutParams retryParams = new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.WRAP_CONTENT, dp(46));
        retryParams.gravity = Gravity.CENTER;
        panel.addView(retry, retryParams);
        return panel;
    }

    private Button toolbarButton(String label) {
        Button button = new Button(this);
        button.setText(label);
        button.setTextColor(Color.rgb(205, 236, 228));
        button.setTextSize(13);
        button.setAllCaps(false);
        button.setMinHeight(0);
        button.setMinWidth(0);
        button.setPadding(dp(6), 0, dp(6), 0);
        GradientDrawable background = new GradientDrawable();
        background.setColor(Color.rgb(24, 43, 43));
        background.setCornerRadius(dp(10));
        background.setStroke(dp(1), Color.rgb(60, 103, 96));
        button.setBackground(background);
        return button;
    }

    private void configureWebView() {
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setAllowFileAccess(true);
        settings.setAllowContentAccess(true);
        settings.setBuiltInZoomControls(true);
        settings.setDisplayZoomControls(false);
        settings.setSupportZoom(true);
        settings.setUseWideViewPort(false);
        settings.setLoadWithOverviewMode(false);
        settings.setMediaPlaybackRequiresUserGesture(true);
        settings.setUserAgentString(settings.getUserAgentString() + " EasyPanelMobile/1.0");
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            settings.setMixedContentMode(WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE);
        }

        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(true);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            cookies.setAcceptThirdPartyCookies(webView, false);
        }

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return handleNavigation(request.getUrl());
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return handleNavigation(Uri.parse(url));
            }

            @Override
            public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
                beginLoading();
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                progressBar.setVisibility(View.GONE);
                errorView.setVisibility(View.GONE);
                injectMobileEnhancements(view);
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) showPageError("无法连接电脑端 Easy Panel。请确认 8190 服务正在运行。");
            }

            @Override
            public void onReceivedError(WebView view, int errorCode, String description, String failingUrl) {
                showPageError("无法连接电脑端 Easy Panel。请确认 8190 服务正在运行。");
            }

            @Override
            public void onReceivedHttpError(WebView view, WebResourceRequest request, android.webkit.WebResourceResponse response) {
                if (request.isForMainFrame() && response.getStatusCode() >= 400) {
                    showPageError("Easy Panel 返回 HTTP " + response.getStatusCode() + "。");
                }
            }

            @Override
            public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
                handler.cancel();
                showPageError("HTTPS 证书校验失败，已停止加载。");
            }
        });

        webView.addJavascriptInterface(new DownloadBridge(), "EasyPanelDownload");

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onProgressChanged(WebView view, int newProgress) {
                progressBar.setProgress(Math.max(0, Math.min(100, newProgress)));
                if (newProgress >= 100) progressBar.setVisibility(View.GONE);
                else progressBar.setVisibility(View.VISIBLE);
            }

            @Override
            public void onReceivedTitle(WebView view, String title) {
                if (titleView != null && title != null && !title.trim().isEmpty()) {
                    titleView.setText(title.trim());
                }
            }

            @Override
            public boolean onShowFileChooser(
                WebView view,
                ValueCallback<Uri[]> callback,
                FileChooserParams params
            ) {
                if (fileChooserCallback != null) fileChooserCallback.onReceiveValue(null);
                fileChooserCallback = callback;
                Intent intent;
                try {
                    intent = params.createIntent();
                } catch (Exception ignored) {
                    intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                    intent.addCategory(Intent.CATEGORY_OPENABLE);
                    intent.setType("image/*");
                }
                try {
                    startActivityForResult(intent, FILE_CHOOSER_REQUEST);
                } catch (ActivityNotFoundException error) {
                    fileChooserCallback = null;
                    callback.onReceiveValue(null);
                    Toast.makeText(AdvancedPanelActivity.this, "系统没有可用的文件选择器", Toast.LENGTH_LONG).show();
                }
                return true;
            }
        });

        webView.setDownloadListener(new DownloadListener() {
            @Override
            public void onDownloadStart(String url, String userAgent, String contentDisposition, String mimetype, long contentLength) {
                beginDownload(new DownloadSpec(url, userAgent, contentDisposition, mimetype));
            }
        });
    }

    private void injectMobileEnhancements(WebView view) {
        view.evaluateJavascript(
            "(function(){"
                + "document.documentElement.classList.add('easy-panel-mobile');"
                + "if(window.__easyPanelMobileDownloadHook)return;"
                + "window.__easyPanelMobileDownloadHook=true;"
                + "document.addEventListener('click',function(event){"
                + "var link=event.target&&event.target.closest?event.target.closest('a[download]'):null;"
                + "if(!link||!link.href||(!link.href.startsWith('blob:')&&!link.href.startsWith('data:')))return;"
                + "event.preventDefault();event.stopPropagation();"
                + "var name=link.download||'easy-panel-download';"
                + "if(link.href.startsWith('data:')){"
                + "var comma=link.href.indexOf(',');"
                + "if(comma<0)return;"
                + "var header=link.href.slice(5,comma),body=link.href.slice(comma+1);"
                + "var mime=(header.split(';')[0]||'application/octet-stream');"
                + "if(header.indexOf(';base64')<0){body=btoa(unescape(encodeURIComponent(decodeURIComponent(body))))}"
                + "window.EasyPanelDownload.saveBase64(name,mime,body);return;"
                + "}"
                + "fetch(link.href).then(function(response){return response.blob()}).then(function(blob){"
                + "var reader=new FileReader();reader.onloadend=function(){"
                + "var result=String(reader.result||''),comma=result.indexOf(',');"
                + "if(comma>=0)window.EasyPanelDownload.saveBase64(name,blob.type||'application/octet-stream',result.slice(comma+1));"
                + "};reader.readAsDataURL(blob);"
                + "}).catch(function(){});"
                + "},true);"
                + "})();",
            null
        );
    }

    private void beginLoading() {
        errorView.setVisibility(View.GONE);
        progressBar.setProgress(5);
        progressBar.setVisibility(View.VISIBLE);
    }

    private void showPageError(String message) {
        progressBar.setVisibility(View.GONE);
        errorMessage.setText(message);
        errorView.setVisibility(View.VISIBLE);
    }

    private boolean handleNavigation(Uri uri) {
        if (uri == null) return true;
        String scheme = uri.getScheme();
        if (scheme == null) return true;
        if (isLocalComfyUi(uri)) {
            Toast.makeText(this, "ComfyUI 只在电脑端运行，高级面板已保留当前页面。", Toast.LENGTH_LONG).show();
            return true;
        }
        if (("http".equalsIgnoreCase(scheme) || "https".equalsIgnoreCase(scheme)) && isPanelOrigin(uri)) {
            return false;
        }
        openExternal(uri);
        return true;
    }

    private boolean isPanelOrigin(Uri uri) {
        return panelScheme.equalsIgnoreCase(uri.getScheme())
            && panelHost.equalsIgnoreCase(uri.getHost())
            && panelPort == (uri.getPort() == -1 ? defaultPort(uri.getScheme()) : uri.getPort());
    }

    private boolean isLocalComfyUi(Uri uri) {
        int port = uri.getPort() == -1 ? defaultPort(uri.getScheme()) : uri.getPort();
        return port == 8188;
    }

    private void openExternal(Uri uri) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, uri));
        } catch (ActivityNotFoundException ignored) {
            Toast.makeText(this, "没有可打开此链接的应用", Toast.LENGTH_LONG).show();
        }
    }

    private void beginDownload(DownloadSpec spec) {
        if (spec == null || spec.url == null || !(spec.url.startsWith("http://") || spec.url.startsWith("https://"))) {
            Toast.makeText(this, "不支持此下载地址", Toast.LENGTH_LONG).show();
            return;
        }
        pendingDownload = spec;
        if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.P
            && checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.WRITE_EXTERNAL_STORAGE}, DOWNLOAD_PERMISSION_REQUEST);
            return;
        }
        enqueueDownload(spec);
    }

    private void enqueueDownload(DownloadSpec spec) {
        try {
            DownloadManager manager = (DownloadManager) getSystemService(DOWNLOAD_SERVICE);
            DownloadManager.Request request = new DownloadManager.Request(Uri.parse(spec.url));
            request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
            request.setDescription("Easy Panel 文件");
            if (spec.mimeType != null && !spec.mimeType.trim().isEmpty()) request.setMimeType(spec.mimeType);
            if (spec.userAgent != null && !spec.userAgent.trim().isEmpty()) request.addRequestHeader("User-Agent", spec.userAgent);
            String cookie = CookieManager.getInstance().getCookie(spec.url);
            if (cookie != null && !cookie.trim().isEmpty()) request.addRequestHeader("Cookie", cookie);
            String filename = uniqueDownloadFilename(sanitizeFilename(URLUtil.guessFileName(spec.url, spec.contentDisposition, spec.mimeType)));
            request.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, filename);
            manager.enqueue(request);
            pendingDownload = null;
            Toast.makeText(this, "已加入下载：" + filename, Toast.LENGTH_LONG).show();
        } catch (Exception error) {
            pendingDownload = null;
            Toast.makeText(this, "下载失败，请稍后重试", Toast.LENGTH_LONG).show();
        }
    }

    private void saveJavascriptDownload(String filename, String mimeType, String base64) {
        if (base64 == null || base64.length() > 120_000_000) {
            runOnUiThread(() -> Toast.makeText(this, "文件过大，无法保存", Toast.LENGTH_LONG).show());
            return;
        }
        final byte[] bytes;
        try {
            bytes = android.util.Base64.decode(base64, android.util.Base64.DEFAULT);
        } catch (IllegalArgumentException error) {
            runOnUiThread(() -> Toast.makeText(this, "文件数据无效", Toast.LENGTH_LONG).show());
            return;
        }
        final JsDownloadSpec spec = new JsDownloadSpec(
            sanitizeFilename(filename),
            mimeType == null || mimeType.trim().isEmpty() ? "application/octet-stream" : mimeType,
            bytes
        );
        runOnUiThread(() -> {
            pendingJsDownload = spec;
            if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.P
                && checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{Manifest.permission.WRITE_EXTERNAL_STORAGE}, DOWNLOAD_PERMISSION_REQUEST);
                return;
            }
            writeJavascriptDownload(spec);
        });
    }

    private void writeJavascriptDownload(JsDownloadSpec spec) {
        if (spec == null) return;
        Uri inserted = null;
        String savedFilename = spec.filename;
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                ContentResolver resolver = getContentResolver();
                savedFilename = uniqueDownloadFilename(spec.filename);
                ContentValues values = new ContentValues();
                values.put(MediaStore.Downloads.DISPLAY_NAME, savedFilename);
                values.put(MediaStore.Downloads.MIME_TYPE, spec.mimeType);
                values.put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/");
                values.put(MediaStore.Downloads.IS_PENDING, 1);
                inserted = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
                if (inserted == null) throw new IllegalStateException("download insert failed");
                try (OutputStream output = resolver.openOutputStream(inserted)) {
                    if (output == null) throw new IllegalStateException("download stream failed");
                    output.write(spec.bytes);
                }
                ContentValues done = new ContentValues();
                done.put(MediaStore.Downloads.IS_PENDING, 0);
                resolver.update(inserted, done, null, null);
            } else {
                File directory = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS);
                if (!directory.exists() && !directory.mkdirs()) throw new IllegalStateException("download directory failed");
                savedFilename = uniqueDownloadFilename(directory, spec.filename);
                File target = new File(directory, savedFilename);
                try (FileOutputStream output = new FileOutputStream(target)) {
                    output.write(spec.bytes);
                }
                sendBroadcast(new Intent(Intent.ACTION_MEDIA_SCANNER_SCAN_FILE, Uri.fromFile(target)));
            }
            pendingJsDownload = null;
            Toast.makeText(this, "已保存到下载：" + savedFilename, Toast.LENGTH_LONG).show();
        } catch (Exception error) {
            if (inserted != null) getContentResolver().delete(inserted, null, null);
            pendingJsDownload = null;
            Toast.makeText(this, "保存下载文件失败", Toast.LENGTH_LONG).show();
        }
    }

    private String uniqueDownloadFilename(String filename) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            File directory = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS);
            return uniqueDownloadFilename(directory, filename);
        }
        String candidate = filename;
        int suffix = 1;
        while (mediaStoreNameExists(candidate)) candidate = withSuffix(filename, suffix++);
        return candidate;
    }

    private String uniqueDownloadFilename(File directory, String filename) {
        String candidate = filename;
        int suffix = 1;
        while (new File(directory, candidate).exists()) candidate = withSuffix(filename, suffix++);
        return candidate;
    }

    private boolean mediaStoreNameExists(String filename) {
        String[] projection = { MediaStore.Downloads.DISPLAY_NAME };
        String selection = MediaStore.Downloads.DISPLAY_NAME + " = ? AND "
            + MediaStore.Downloads.RELATIVE_PATH + " = ?";
        try (android.database.Cursor cursor = getContentResolver().query(
            MediaStore.Downloads.EXTERNAL_CONTENT_URI,
            projection,
            selection,
            new String[]{ filename, Environment.DIRECTORY_DOWNLOADS + "/" },
            null
        )) {
            return cursor != null && cursor.moveToFirst();
        } catch (Exception ignored) {
            return false;
        }
    }

    private String withSuffix(String filename, int suffix) {
        int dot = filename.lastIndexOf('.');
        if (dot > 0 && dot < filename.length() - 1) {
            return filename.substring(0, dot) + " (" + suffix + ")" + filename.substring(dot);
        }
        return filename + " (" + suffix + ")";
    }

    private String sanitizeFilename(String filename) {
        String safe = filename == null ? "easy-panel-download" : filename.trim();
        safe = safe.replaceAll("[\\\\/:*?\"<>|]", "_");
        if (safe.isEmpty() || ".".equals(safe) || "..".equals(safe)) safe = "easy-panel-download";
        return safe.length() > 180 ? safe.substring(0, 180) : safe;
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != FILE_CHOOSER_REQUEST || fileChooserCallback == null) return;
        Uri[] results = WebChromeClient.FileChooserParams.parseResult(resultCode, data);
        fileChooserCallback.onReceiveValue(results);
        fileChooserCallback = null;
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != DOWNLOAD_PERMISSION_REQUEST) return;
        DownloadSpec download = pendingDownload;
        pendingDownload = null;
        if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED && download != null) {
            enqueueDownload(download);
        } else if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED && pendingJsDownload != null) {
            JsDownloadSpec javascriptDownload = pendingJsDownload;
            writeJavascriptDownload(javascriptDownload);
        } else {
            pendingJsDownload = null;
            Toast.makeText(this, "没有存储权限，无法保存下载文件", Toast.LENGTH_LONG).show();
        }
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        if (webView != null) webView.saveState(outState);
        super.onSaveInstanceState(outState);
    }

    @Override
    public void onBackPressed() {
        goBackOrFinish();
    }

    private void goBackOrFinish() {
        if (webView != null && webView.canGoBack()) webView.goBack();
        else finish();
    }

    @Override
    protected void onDestroy() {
        if (fileChooserCallback != null) {
            fileChooserCallback.onReceiveValue(null);
            fileChooserCallback = null;
        }
        if (webView != null) {
            webView.stopLoading();
            webView.setWebChromeClient(null);
            webView.setWebViewClient(null);
            webView.destroy();
            webView = null;
        }
        super.onDestroy();
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private static final class DownloadSpec {
        final String url;
        final String userAgent;
        final String contentDisposition;
        final String mimeType;

        DownloadSpec(String url, String userAgent, String contentDisposition, String mimeType) {
            this.url = url;
            this.userAgent = userAgent;
            this.contentDisposition = contentDisposition;
            this.mimeType = mimeType;
        }
    }

    private final class DownloadBridge {
        @JavascriptInterface
        public void saveBase64(String filename, String mimeType, String base64) {
            saveJavascriptDownload(filename, mimeType, base64);
        }
    }

    private static final class JsDownloadSpec {
        final String filename;
        final String mimeType;
        final byte[] bytes;

        JsDownloadSpec(String filename, String mimeType, byte[] bytes) {
            this.filename = filename;
            this.mimeType = mimeType;
            this.bytes = bytes;
        }
    }
}
