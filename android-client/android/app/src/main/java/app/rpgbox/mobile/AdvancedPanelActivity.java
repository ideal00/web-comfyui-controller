package app.rpgbox.mobile;

import android.Manifest;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.app.Activity;
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
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.HashMap;
import java.util.Map;

/** Native container for the computer's full Easy Panel web UI. */
@SuppressWarnings("deprecation")
public class AdvancedPanelActivity extends Activity {

    public static final String EXTRA_URL = "easy_panel_url";
    public static final String EXTRA_TOKEN = "easy_panel_token";
    static final int MAX_PANEL_TOKEN_LENGTH = 4096;
    private static final int MAX_CLIPBOARD_TEXT_LENGTH = 65536;
    private static final int FILE_CHOOSER_REQUEST = 4101;
    private static final int DOWNLOAD_PERMISSION_REQUEST = 4102;

    private WebView webView;
    private ProgressBar progressBar;
    private View errorView;
    private TextView errorMessage;
    private TextView titleView;
    private String panelUrl;
    private String panelToken;
    private String panelScheme;
    private String panelHost;
    private int panelPort;
    private volatile String verifiedPageUrl;
    private ValueCallback<Uri[]> fileChooserCallback;
    private DownloadSpec pendingDownload;
    private JsDownloadSpec pendingJsDownload;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(Color.rgb(11, 18, 21));
        getWindow().setNavigationBarColor(Color.rgb(11, 18, 21));

        panelUrl = getIntent().getStringExtra(EXTRA_URL);
        panelToken = getIntent().getStringExtra(EXTRA_TOKEN);
        if (panelToken == null) panelToken = "";
        panelToken = panelToken.trim();
        if (panelToken.length() > MAX_PANEL_TOKEN_LENGTH) {
            Toast.makeText(this, "高级面板 Token 无效", Toast.LENGTH_LONG).show();
            finish();
            return;
        }
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
        loadPanelUrl();
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
        refresh.setOnClickListener(view -> loadPanelUrl());
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
        retry.setOnClickListener(view -> loadPanelUrl());
        LinearLayout.LayoutParams retryParams = new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.WRAP_CONTENT, dp(46));
        retryParams.gravity = Gravity.CENTER;
        panel.addView(retry, retryParams);
        return panel;
    }

    private void loadPanelUrl() {
        if (webView == null || panelUrl == null) return;
        if (panelToken == null || panelToken.isEmpty()) {
            webView.loadUrl(panelUrl);
            return;
        }
        Map<String, String> headers = new HashMap<>();
        headers.put("X-RPG-Token", panelToken);
        webView.loadUrl(panelUrl, headers);
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
                verifiedPageUrl = null;
                beginLoading();
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                progressBar.setVisibility(View.GONE);
                errorView.setVisibility(View.GONE);
                if (isPanelOriginUrl(url)) {
                    verifiedPageUrl = url;
                    injectMobileEnhancements(view);
                }
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
        webView.addJavascriptInterface(new ClipboardBridge(), "EasyPanelClipboard");

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
                beginDownload(new DownloadSpec(url, userAgent, contentDisposition, mimetype, "", contentLength, ""));
            }
        });
    }

    private void injectMobileEnhancements(WebView view) {
        view.evaluateJavascript(
            "(function(){"
                + "document.documentElement.classList.add('easy-panel-mobile');"
                + "if(!window.EasyPanelDownload||window.__easyPanelMobileDownloadHook)return;"
                + "window.__easyPanelMobileDownloadHook=true;"
                + "var maxSize=90*1024*1024;"
                + "function absolute(raw){try{return new URL(String(raw||''),document.baseURI)}catch(e){return null}}"
                + "function isHttp(url){return !!url&&(url.protocol==='http:'||url.protocol==='https:')}"
                + "function isSameOrigin(url){if(!isHttp(url)||url.origin!==location.origin||url.username||url.password||url.hash)return false;return !/(?:^|&)(?:token|authorization|api_key|apikey|secret)(?:=|&|$)/i.test((url.search||'').slice(1))}"
                + "function filenameFromUrl(url){try{var queryName=url.searchParams&&url.searchParams.get('name');if(queryName)return queryName;var path=decodeURIComponent(url.pathname||''),parts=path.split('/');return parts[parts.length-1]||''}catch(e){return ''}}"
                + "function mimeFor(link){return link.getAttribute('type')||''}"
                + "function sendUrl(url,name,mime){if(!url||!isSameOrigin(url)||!window.EasyPanelDownload.downloadUrl)return false;window.EasyPanelDownload.downloadUrl(url.href,name||filenameFromUrl(url)||'easy-panel-download',mime||'');return true}"
                + "function sendBlob(raw,name,mime){if(!window.EasyPanelDownload.saveBase64)return false;var text=String(raw||'');fetch(text).then(function(response){if(!response.ok)throw Error('download');return response.blob()}).then(function(blob){if(blob.size>maxSize)throw Error('large');var reader=new FileReader();reader.onloadend=function(){var result=String(reader.result||''),comma=result.indexOf(',');if(comma>=0)window.EasyPanelDownload.saveBase64(name||'easy-panel-download',blob.type||mime||'application/octet-stream',result.slice(comma+1))};reader.readAsDataURL(blob)}).catch(function(){});return true}"
                + "function linkFromTarget(target){while(target&&target!==document){if(target.tagName&&target.tagName.toLowerCase()==='a')return target;target=target.parentElement}return null}"
                + "function markViewerDownload(){var link=document.getElementById('panelImageViewerOpen');if(!link)return;if(link.textContent!=='下载原图')link.textContent='下载原图';link.removeAttribute('target');link.setAttribute('download','');link.title='保存原图到 Downloads'}"
                + "markViewerDownload();"
                + "if(window.MutationObserver)new MutationObserver(markViewerDownload).observe(document.documentElement,{subtree:true,childList:true,attributes:true,attributeFilter:['href']});"
                + "document.addEventListener('click',function(event){"
                + "var link=linkFromTarget(event.target);if(!link)return;"
                + "var isViewer=link.id==='panelImageViewerOpen',hasDownload=link.hasAttribute('download');"
                + "if(!isViewer&&!hasDownload)return;"
                + "if(event.ctrlKey||event.metaKey||event.shiftKey||event.button===1)return;"
                + "var raw=link.getAttribute('href')||link.href||'';if(!raw)return;"
                + "var name=link.getAttribute('download')||'';"
                + "if(/^blob:|^data:/i.test(raw)){event.preventDefault();event.stopPropagation();sendBlob(raw,name,mimeFor(link));return}"
                + "var url=absolute(raw);if(!url||!isSameOrigin(url))return;"
                + "event.preventDefault();event.stopPropagation();sendUrl(url,name||filenameFromUrl(url),mimeFor(link));"
                + "},true);"
                + "var originalOpen=window.open;window.open=function(raw,target,features){var text=String(raw||'');if(/^blob:|^data:/i.test(text)){if(sendBlob(text,'',''))return null}var url=absolute(text);if(url&&isSameOrigin(url)&&(url.pathname==='/output'||url.pathname==='/pose-editor-workflow.json')){if(sendUrl(url,filenameFromUrl(url),'') )return null}return typeof originalOpen==='function'?originalOpen.apply(window,arguments):null};"
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
        return uri != null && isPanelOriginUrl(uri.toString());
    }

    private boolean isPanelOriginUrl(String rawUrl) {
        return DownloadSupport.isSameHttpOrigin(rawUrl, panelScheme, panelHost, panelPort);
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

    private boolean isTrustedBridgePage() {
        return verifiedPageUrl != null && isPanelOriginUrl(verifiedPageUrl);
    }

    private boolean isAllowedPanelDownloadUrl(String rawUrl) {
        return DownloadSupport.isSameHttpOrigin(rawUrl, panelScheme, panelHost, panelPort);
    }

    private void beginDownload(DownloadSpec spec) {
        if (!isTrustedBridgePage()) {
            Toast.makeText(this, "下载来源未验证，已取消保存", Toast.LENGTH_LONG).show();
            return;
        }
        if (spec == null || !isAllowedPanelDownloadUrl(spec.url)) {
            Toast.makeText(this, "不支持此下载地址", Toast.LENGTH_LONG).show();
            return;
        }
        if (spec.contentLength > DownloadSupport.MAX_DOWNLOAD_BYTES) {
            Toast.makeText(this, "文件超过 90 MB，无法保存", Toast.LENGTH_LONG).show();
            return;
        }
        pendingDownload = spec;
        if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.P
            && checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.WRITE_EXTERNAL_STORAGE}, DOWNLOAD_PERMISSION_REQUEST);
            return;
        }
        pendingDownload = null;
        startUrlDownload(spec);
    }

    private void startUrlDownload(DownloadSpec spec) {
        if (spec == null) return;
        String cookie = "";
        try {
            cookie = DownloadSupport.safeHeaderValue(CookieManager.getInstance().getCookie(spec.url), 8192);
        } catch (Exception ignored) {
            // The protected Easy Panel route will reject a missing session cookie.
        }
        final DownloadSpec request = new DownloadSpec(
            spec.url,
            DownloadSupport.safeHeaderValue(spec.userAgent, 512),
            spec.contentDisposition,
            spec.mimeType,
            spec.requestedFilename,
            spec.contentLength,
            cookie
        );
        Toast.makeText(this, "正在下载到系统 Downloads…", Toast.LENGTH_SHORT).show();
        new Thread(() -> {
            try {
                String savedFilename = downloadUrl(request);
                runOnUiThread(() -> Toast.makeText(
                    this,
                    "已保存到下载：" + savedFilename,
                    Toast.LENGTH_LONG
                ).show());
            } catch (Exception error) {
                runOnUiThread(() -> Toast.makeText(
                    this,
                    "下载失败，文件未保存",
                    Toast.LENGTH_LONG
                ).show());
            }
        }, "easy-panel-http-download").start();
    }

    private String downloadUrl(DownloadSpec spec) throws Exception {
        String currentUrl = spec.url;
        HttpURLConnection connection = null;
        try {
            for (int redirect = 0; redirect < 5; redirect++) {
                if (!isAllowedPanelDownloadUrl(currentUrl)) throw new SecurityException("download origin rejected");
                URL requestUrl = new URL(currentUrl);
                connection = (HttpURLConnection) requestUrl.openConnection();
                connection.setInstanceFollowRedirects(false);
                connection.setConnectTimeout(15_000);
                connection.setReadTimeout(120_000);
                connection.setRequestMethod("GET");
                connection.setDoInput(true);
                if (!spec.userAgent.isEmpty()) connection.setRequestProperty("User-Agent", spec.userAgent);
                if (!spec.cookie.isEmpty()) connection.setRequestProperty("Cookie", spec.cookie);

                int status = connection.getResponseCode();
                if (status >= 300 && status < 400) {
                    String location = connection.getHeaderField("Location");
                    if (location == null || location.trim().isEmpty()) throw new IOException("redirect missing");
                    String nextUrl = new URL(requestUrl, location).toExternalForm();
                    connection.disconnect();
                    connection = null;
                    if (!isAllowedPanelDownloadUrl(nextUrl)) throw new SecurityException("redirect origin rejected");
                    currentUrl = nextUrl;
                    continue;
                }
                if (status < 200 || status >= 300) throw new IOException("download HTTP error");

                long responseLength = connection.getContentLengthLong();
                if (responseLength > DownloadSupport.MAX_DOWNLOAD_BYTES) throw new DownloadTooLargeException();
                String contentDisposition = connection.getHeaderField("Content-Disposition");
                if (contentDisposition == null || contentDisposition.trim().isEmpty()) {
                    contentDisposition = spec.contentDisposition;
                }
                String mimeType = DownloadSupport.normalizeMimeType(
                    spec.mimeType == null || spec.mimeType.trim().isEmpty()
                        ? connection.getContentType()
                        : spec.mimeType
                );
                String filename = spec.requestedFilename;
                if (filename == null || filename.trim().isEmpty()) {
                    filename = DownloadSupport.filenameFromContentDisposition(contentDisposition);
                }
                if (filename == null || filename.trim().isEmpty()) {
                    filename = URLUtil.guessFileName(currentUrl, contentDisposition, mimeType);
                }
                filename = DownloadSupport.sanitizeFilename(filename);
                try (InputStream input = connection.getInputStream()) {
                    return writeHttpResponseToDownloads(filename, mimeType, input, responseLength);
                } finally {
                    connection.disconnect();
                    connection = null;
                }
            }
            throw new IOException("too many redirects");
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    private String writeHttpResponseToDownloads(
        String filename,
        String mimeType,
        InputStream input,
        long expectedLength
    ) throws Exception {
        if (expectedLength > DownloadSupport.MAX_DOWNLOAD_BYTES) throw new DownloadTooLargeException();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ContentResolver resolver = getContentResolver();
            String savedFilename = uniqueDownloadFilename(DownloadSupport.sanitizeFilename(filename));
            ContentValues values = new ContentValues();
            values.put(MediaStore.Downloads.DISPLAY_NAME, savedFilename);
            values.put(MediaStore.Downloads.MIME_TYPE, DownloadSupport.normalizeMimeType(mimeType));
            values.put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/");
            values.put(MediaStore.Downloads.IS_PENDING, 1);
            Uri inserted = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
            if (inserted == null) throw new IllegalStateException("download insert failed");
            try {
                try (OutputStream output = resolver.openOutputStream(inserted)) {
                    if (output == null) throw new IllegalStateException("download stream failed");
                    copyLimited(input, output, expectedLength);
                }
                ContentValues done = new ContentValues();
                done.put(MediaStore.Downloads.IS_PENDING, 0);
                if (resolver.update(inserted, done, null, null) <= 0) {
                    throw new IllegalStateException("download finalize failed");
                }
                return savedFilename;
            } catch (Exception error) {
                resolver.delete(inserted, null, null);
                throw error;
            }
        }

        File directory = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS);
        if (!directory.exists() && !directory.mkdirs()) throw new IllegalStateException("download directory failed");
        String savedFilename = uniqueDownloadFilename(directory, DownloadSupport.sanitizeFilename(filename));
        File target = new File(directory, savedFilename);
        try {
            try (OutputStream output = new FileOutputStream(target)) {
                copyLimited(input, output, expectedLength);
            }
            sendBroadcast(new Intent(Intent.ACTION_MEDIA_SCANNER_SCAN_FILE, Uri.fromFile(target)));
            return savedFilename;
        } catch (Exception error) {
            target.delete();
            throw error;
        }
    }

    private void copyLimited(InputStream input, OutputStream output, long expectedLength) throws IOException {
        if (expectedLength > DownloadSupport.MAX_DOWNLOAD_BYTES) throw new DownloadTooLargeException();
        byte[] buffer = new byte[32 * 1024];
        long total = 0;
        int count;
        while ((count = input.read(buffer)) != -1) {
            total += count;
            if (total > DownloadSupport.MAX_DOWNLOAD_BYTES) throw new DownloadTooLargeException();
            output.write(buffer, 0, count);
        }
    }

    private void saveJavascriptDownload(String filename, String mimeType, String base64) {
        if (!isTrustedBridgePage()) {
            runOnUiThread(() -> Toast.makeText(this, "下载来源未验证，已取消保存", Toast.LENGTH_LONG).show());
            return;
        }
        long maxBase64Length = ((DownloadSupport.MAX_DOWNLOAD_BYTES + 2) / 3) * 4 + 4;
        if (base64 == null || (long) base64.length() > maxBase64Length) {
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
        if (bytes.length > DownloadSupport.MAX_DOWNLOAD_BYTES) {
            runOnUiThread(() -> Toast.makeText(this, "文件超过 90 MB，无法保存", Toast.LENGTH_LONG).show());
            return;
        }
        final JsDownloadSpec spec = new JsDownloadSpec(
            DownloadSupport.sanitizeFilename(filename),
            DownloadSupport.normalizeMimeType(mimeType),
            bytes
        );
        runOnUiThread(() -> {
            if (!isTrustedBridgePage()) {
                Toast.makeText(this, "下载来源未验证，已取消保存", Toast.LENGTH_LONG).show();
                return;
            }
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
        pendingJsDownload = null;
        new Thread(() -> {
            try (InputStream input = new java.io.ByteArrayInputStream(spec.bytes)) {
                String savedFilename = writeHttpResponseToDownloads(
                    spec.filename,
                    spec.mimeType,
                    input,
                    spec.bytes.length
                );
                runOnUiThread(() -> Toast.makeText(
                    this,
                    "已保存到下载：" + savedFilename,
                    Toast.LENGTH_LONG
                ).show());
            } catch (Exception error) {
                runOnUiThread(() -> Toast.makeText(
                    this,
                    "保存下载文件失败，文件未保存",
                    Toast.LENGTH_LONG
                ).show());
            }
        }, "easy-panel-js-download").start();
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
        JsDownloadSpec javascriptDownload = pendingJsDownload;
        pendingDownload = null;
        pendingJsDownload = null;
        if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED && download != null) {
            startUrlDownload(download);
        } else if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED && javascriptDownload != null) {
            writeJavascriptDownload(javascriptDownload);
        } else {
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
        verifiedPageUrl = null;
        pendingDownload = null;
        pendingJsDownload = null;
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
        final String requestedFilename;
        final long contentLength;
        final String cookie;

        DownloadSpec(
            String url,
            String userAgent,
            String contentDisposition,
            String mimeType,
            String requestedFilename,
            long contentLength,
            String cookie
        ) {
            this.url = url;
            this.userAgent = userAgent;
            this.contentDisposition = contentDisposition;
            this.mimeType = mimeType;
            this.requestedFilename = requestedFilename == null ? "" : requestedFilename;
            this.contentLength = contentLength;
            this.cookie = cookie == null ? "" : cookie;
        }
    }

    private final class DownloadBridge {
        @JavascriptInterface
        public void downloadUrl(String url, String filename, String mimeType) {
            runOnUiThread(() -> beginDownload(new DownloadSpec(
                url,
                "",
                "",
                mimeType,
                filename,
                -1,
                ""
            )));
        }

        @JavascriptInterface
        public void saveBase64(String filename, String mimeType, String base64) {
            saveJavascriptDownload(filename, mimeType, base64);
        }
    }

    /** Minimal, origin-checked bridge for page actions that need system clipboard access. */
    private final class ClipboardBridge {
        @JavascriptInterface
        public boolean copyText(String text) {
            if (!isTrustedBridgePage() || text == null || text.isEmpty()
                || text.length() > MAX_CLIPBOARD_TEXT_LENGTH) return false;
            try {
                ClipboardManager clipboard = (ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
                if (clipboard == null) return false;
                clipboard.setPrimaryClip(ClipData.newPlainText("Easy Panel", text));
                return true;
            } catch (Exception ignored) {
                return false;
            }
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

    private static final class DownloadTooLargeException extends IOException {
        DownloadTooLargeException() {
            super("download exceeds size limit");
        }
    }
}
