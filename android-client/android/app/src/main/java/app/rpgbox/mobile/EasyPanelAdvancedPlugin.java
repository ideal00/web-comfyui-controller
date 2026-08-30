package app.rpgbox.mobile;

import android.Manifest;
import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;
import com.getcapacitor.annotation.CapacitorPlugin;

@CapacitorPlugin(
    name = "EasyPanelAdvanced",
    permissions = {
        @Permission(alias = "storage", strings = { Manifest.permission.WRITE_EXTERNAL_STORAGE })
    }
)
public class EasyPanelAdvancedPlugin extends Plugin {

    @PluginMethod
    public void open(PluginCall call) {
        String url = call.getString("url", "");
        if (!AdvancedPanelActivity.isSafePanelUrl(url)) {
            call.reject("高级面板地址无效，只支持 http/https 的 Easy Panel 根地址。\n");
            return;
        }

        Intent intent = new Intent(getActivity(), AdvancedPanelActivity.class);
        intent.putExtra(AdvancedPanelActivity.EXTRA_URL, url.trim());
        getActivity().startActivity(intent);
        JSObject result = new JSObject();
        result.put("opened", true);
        call.resolve(result);
    }

    /** Save the quick page's image into the user-visible public Downloads folder. */
    @PluginMethod
    public void saveBase64(PluginCall call) {
        String filename = call.getString("filename", "easy-panel-download");
        String mimeType = call.getString("mimeType", "application/octet-stream");
        String base64 = call.getString("base64", "");
        if (base64 == null || base64.trim().isEmpty()) {
            call.reject("下载内容为空，无法保存。");
            return;
        }
        long maxBase64Length = ((DownloadSupport.MAX_DOWNLOAD_BYTES + 2) / 3) * 4 + 4;
        if ((long) base64.length() > maxBase64Length) {
            call.reject("文件过大，无法保存到下载目录。");
            return;
        }
        if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.P
            && getActivity().checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
            call.getData().put("filename", filename);
            call.getData().put("mimeType", mimeType);
            call.getData().put("base64", base64);
            requestPermissionForAlias("storage", call, "storagePermissionCallback");
            return;
        }
        persistBase64(call, filename, mimeType, base64);
    }

    @PermissionCallback
    private void storagePermissionCallback(PluginCall call) {
        if (getActivity().checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
            call.reject("没有存储权限，无法保存下载文件。");
            return;
        }
        persistBase64(
            call,
            call.getString("filename", "easy-panel-download"),
            call.getString("mimeType", "application/octet-stream"),
            call.getString("base64", "")
        );
    }

    private void persistBase64(PluginCall call, String filename, String mimeType, String base64) {
        final byte[] bytes;
        try {
            bytes = android.util.Base64.decode(base64, android.util.Base64.DEFAULT);
        } catch (IllegalArgumentException error) {
            call.reject("下载内容无效，无法保存。");
            return;
        }
        if (bytes.length > DownloadSupport.MAX_DOWNLOAD_BYTES) {
            call.reject("文件过大，无法保存到下载目录。");
            return;
        }

        final String safeFilename = DownloadSupport.sanitizeFilename(filename);
        final String safeMimeType = DownloadSupport.normalizeMimeType(mimeType);
        new Thread(() -> {
            UriResult result = null;
            try {
                result = writeToDownloads(safeFilename, safeMimeType, bytes);
                JSObject response = new JSObject();
                response.put("saved", true);
                response.put("filename", result.filename);
                response.put("location", result.location);
                getActivity().runOnUiThread(() -> call.resolve(response));
            } catch (Exception error) {
                if (result != null && result.uri != null) getActivity().getContentResolver().delete(result.uri, null, null);
                getActivity().runOnUiThread(() -> call.reject("保存下载文件失败，请检查系统存储空间。"));
            }
        }, "easy-panel-download").start();
    }

    private UriResult writeToDownloads(String filename, String mimeType, byte[] bytes) throws Exception {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ContentResolver resolver = getActivity().getContentResolver();
            String uniqueFilename = uniqueMediaStoreFilename(filename);
            ContentValues values = new ContentValues();
            values.put(MediaStore.Downloads.DISPLAY_NAME, uniqueFilename);
            values.put(MediaStore.Downloads.MIME_TYPE, mimeType);
            values.put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/");
            values.put(MediaStore.Downloads.IS_PENDING, 1);
            android.net.Uri uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
            if (uri == null) throw new IllegalStateException("download insert failed");
            try (OutputStream output = resolver.openOutputStream(uri)) {
                if (output == null) throw new IllegalStateException("download stream failed");
                output.write(bytes);
            }
            ContentValues done = new ContentValues();
            done.put(MediaStore.Downloads.IS_PENDING, 0);
            resolver.update(uri, done, null, null);
            return new UriResult(uri, uniqueFilename, "Downloads/" + uniqueFilename);
        }

        File directory = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS);
        if (!directory.exists() && !directory.mkdirs()) throw new IllegalStateException("download directory failed");
        String uniqueFilename = uniqueFileName(directory, filename);
        File target = new File(directory, uniqueFilename);
        try (FileOutputStream output = new FileOutputStream(target)) {
            output.write(bytes);
        }
        getActivity().sendBroadcast(new Intent(Intent.ACTION_MEDIA_SCANNER_SCAN_FILE, android.net.Uri.fromFile(target)));
        return new UriResult(null, uniqueFilename, "Downloads/" + uniqueFilename);
    }

    private String uniqueMediaStoreFilename(String filename) {
        String candidate = filename;
        int suffix = 1;
        ContentResolver resolver = getActivity().getContentResolver();
        while (mediaStoreNameExists(resolver, candidate)) {
            candidate = withSuffix(filename, suffix++);
        }
        return candidate;
    }

    private boolean mediaStoreNameExists(ContentResolver resolver, String filename) {
        String[] projection = { MediaStore.Downloads.DISPLAY_NAME };
        String selection = MediaStore.Downloads.DISPLAY_NAME + " = ? AND "
            + MediaStore.Downloads.RELATIVE_PATH + " = ?";
        try (android.database.Cursor cursor = resolver.query(
            MediaStore.Downloads.EXTERNAL_CONTENT_URI,
            projection,
            selection,
            new String[]{ filename, Environment.DIRECTORY_DOWNLOADS + "/" },
            null
        )) {
            return cursor != null && cursor.moveToFirst();
        } catch (Exception ignored) {
            // If a provider does not expose the optional query, MediaStore
            // still creates a separate entry instead of overwriting a file.
            return false;
        }
    }

    private String uniqueFileName(File directory, String filename) {
        String candidate = filename;
        int suffix = 1;
        while (new File(directory, candidate).exists()) candidate = withSuffix(filename, suffix++);
        return candidate;
    }

    private String withSuffix(String filename, int suffix) {
        int dot = filename.lastIndexOf('.');
        if (dot > 0 && dot < filename.length() - 1) {
            return filename.substring(0, dot) + " (" + suffix + ")" + filename.substring(dot);
        }
        return filename + " (" + suffix + ")";
    }

    private static final class UriResult {
        final android.net.Uri uri;
        final String filename;
        final String location;

        UriResult(android.net.Uri uri, String filename, String location) {
            this.uri = uri;
            this.filename = filename;
            this.location = location;
        }
    }
}
