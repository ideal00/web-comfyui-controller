package app.rpgbox.mobile;

import android.os.Bundle;
import android.os.SystemClock;
import android.webkit.WebView;
import android.widget.Toast;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    private long lastBackPressAt = 0;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(EasyPanelAdvancedPlugin.class);
        super.onCreate(savedInstanceState);
    }

    @Override
    public void onBackPressed() {
        WebView webView = bridge == null ? null : bridge.getWebView();
        if (webView == null) {
            confirmExit();
            return;
        }
        webView.evaluateJavascript("(function(){try{return window.__easyPanelHandleBack?.()===true}catch(e){return false}})()", result -> {
            if (!"true".equals(result)) runOnUiThread(this::confirmExit);
        });
    }

    private void confirmExit() {
        long now = SystemClock.elapsedRealtime();
        if (now - lastBackPressAt < 2000) {
            moveTaskToBack(true);
        } else {
            lastBackPressAt = now;
            Toast.makeText(this, "再按一次返回键退出应用", Toast.LENGTH_SHORT).show();
        }
    }
}
