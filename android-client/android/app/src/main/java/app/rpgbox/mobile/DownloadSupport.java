package app.rpgbox.mobile;

import java.net.URI;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Small, Android-free helpers shared by the advanced and quick download paths. */
final class DownloadSupport {
    static final long MAX_DOWNLOAD_BYTES = 90L * 1024L * 1024L;
    static final String FALLBACK_FILENAME = "easy-panel-download";
    static final String FALLBACK_MIME_TYPE = "application/octet-stream";
    private static final int MAX_FILENAME_LENGTH = 180;
    private static final Pattern MIME_TYPE = Pattern.compile(
        "^[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+$",
        Pattern.CASE_INSENSITIVE
    );
    private static final Pattern FILENAME_STAR = Pattern.compile(
        "(?:^|;)\\s*filename\\*\\s*=\\s*(?:UTF-8''|\\\"?)([^;\\\"]+)\\\"?",
        Pattern.CASE_INSENSITIVE
    );
    private static final Pattern FILENAME = Pattern.compile(
        "(?:^|;)\\s*filename\\s*=\\s*(?:\\\"([^\\\"]*)\\\"|([^;\\s]+))",
        Pattern.CASE_INSENSITIVE
    );
    private static final String[] RESERVED_NAMES = {
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
    };

    private DownloadSupport() {
    }

    static String sanitizeFilename(String raw) {
        String safe = raw == null ? "" : raw.trim();
        safe = safe.replaceAll("[\\u0000-\\u001F\\u007F]", "_");
        safe = safe.replaceAll("[\\\\/:*?\"<>|]", "_");
        safe = safe.replace("..", "_");
        safe = safe.replaceAll("^[. ]+", "").replaceAll("[. ]+$", "");
        if (safe.isEmpty()) safe = FALLBACK_FILENAME;

        int dot = safe.indexOf('.');
        String base = (dot > 0 ? safe.substring(0, dot) : safe).toUpperCase(Locale.US);
        if (isReservedName(base)) safe = "_" + safe;
        if (safe.length() > MAX_FILENAME_LENGTH) safe = safe.substring(0, MAX_FILENAME_LENGTH);
        return safe.isEmpty() ? FALLBACK_FILENAME : safe;
    }

    static String normalizeMimeType(String raw) {
        if (raw == null) return FALLBACK_MIME_TYPE;
        String value = raw.trim();
        int parameters = value.indexOf(';');
        if (parameters >= 0) value = value.substring(0, parameters).trim();
        value = value.toLowerCase(Locale.US);
        return MIME_TYPE.matcher(value).matches() ? value : FALLBACK_MIME_TYPE;
    }

    static String filenameFromContentDisposition(String header) {
        if (header == null || header.trim().isEmpty()) return "";
        Matcher extended = FILENAME_STAR.matcher(header);
        if (extended.find()) return decodeRfc5987(extended.group(1));
        Matcher regular = FILENAME.matcher(header);
        if (regular.find()) return regular.group(1) != null ? regular.group(1) : regular.group(2);
        return "";
    }

    static boolean isSameHttpOrigin(String rawUrl, String expectedScheme, String expectedHost, int expectedPort) {
        if (rawUrl == null || expectedScheme == null || expectedHost == null) return false;
        try {
            URI uri = new URI(rawUrl.trim());
            String scheme = uri.getScheme();
            String host = uri.getHost();
            if (!("http".equalsIgnoreCase(scheme) || "https".equalsIgnoreCase(scheme))) return false;
            if (uri.getUserInfo() != null || uri.getFragment() != null || host == null) return false;
            int port = uri.getPort() == -1 ? defaultPort(scheme) : uri.getPort();
            return expectedScheme.equalsIgnoreCase(scheme)
                && expectedHost.equalsIgnoreCase(host)
                && expectedPort == port
                && !hasSensitiveQuery(uri.getRawQuery());
        } catch (Exception ignored) {
            return false;
        }
    }

    static String safeHeaderValue(String raw, int maxLength) {
        if (raw == null || raw.isEmpty()) return "";
        StringBuilder value = new StringBuilder(Math.min(raw.length(), maxLength));
        for (int index = 0; index < raw.length() && value.length() < maxLength; index++) {
            char current = raw.charAt(index);
            if (current >= 0x20 && current != 0x7f) value.append(current);
        }
        return value.toString();
    }

    private static int defaultPort(String scheme) {
        return "https".equalsIgnoreCase(scheme) ? 443 : 80;
    }

    private static boolean isReservedName(String base) {
        for (String reserved : RESERVED_NAMES) {
            if (reserved.equals(base)) return true;
        }
        return false;
    }

    private static boolean hasSensitiveQuery(String rawQuery) {
        if (rawQuery == null || rawQuery.isEmpty()) return false;
        for (String pair : rawQuery.split("&")) {
            String key = pair;
            int equals = pair.indexOf('=');
            if (equals >= 0) key = pair.substring(0, equals);
            try {
                key = URLDecoder.decode(key, StandardCharsets.UTF_8.name());
            } catch (Exception ignored) {
                return true;
            }
            key = key.toLowerCase(Locale.US);
            if (key.contains("token") || key.contains("authorization")
                || key.contains("api_key") || key.contains("apikey") || key.contains("secret")) {
                return true;
            }
        }
        return false;
    }

    private static String decodeRfc5987(String value) {
        try {
            return URLDecoder.decode(value.replace("+", "%2B"), StandardCharsets.UTF_8.name());
        } catch (Exception ignored) {
            return value;
        }
    }
}
