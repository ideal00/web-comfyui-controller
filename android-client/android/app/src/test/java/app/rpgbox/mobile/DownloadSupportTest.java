package app.rpgbox.mobile;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class DownloadSupportTest {

    @Test
    public void contentDispositionPrefersRfc5987Filename() {
        String header = "attachment; filename=\"fallback.txt\"; "
            + "filename*=UTF-8''%E6%B5%8B%E8%AF%95%20image.png";
        assertEquals("测试 image.png", DownloadSupport.filenameFromContentDisposition(header));
    }

    @Test
    public void dangerousFilenamesBecomeSafeUniqueBasenames() {
        String safe = DownloadSupport.sanitizeFilename("..\\bad:/name\u0000?.png");
        assertFalse(safe.contains(".."));
        assertFalse(safe.contains("\\"));
        assertFalse(safe.contains("/"));
        assertFalse(safe.indexOf('\u0000') >= 0);
        assertEquals("_CON.txt", DownloadSupport.sanitizeFilename("CON.txt"));

        String longName = DownloadSupport.sanitizeFilename(new String(new char[240]).replace('\0', 'x'));
        assertEquals(180, longName.length());
    }

    @Test
    public void mimeAndHeadersAreNormalized() {
        assertEquals("image/png", DownloadSupport.normalizeMimeType("IMAGE/PNG; charset=utf-8"));
        assertEquals("application/octet-stream", DownloadSupport.normalizeMimeType("text/plain\r\nX-Evil: yes"));
        assertEquals("abcX", DownloadSupport.safeHeaderValue("a\r\nb\u0000cX", 20));
    }

    @Test
    public void downloadsStayOnVerifiedEasyPanelOrigin() {
        assertTrue(DownloadSupport.isSameHttpOrigin(
            "http://lan-host:8190/output?name=image.png",
            "http",
            "lan-host",
            8190
        ));
        assertFalse(DownloadSupport.isSameHttpOrigin(
            "http://other-host:8190/output?name=image.png",
            "http",
            "lan-host",
            8190
        ));
        assertFalse(DownloadSupport.isSameHttpOrigin(
            "http://lan-host:8190@other-host/output?name=image.png",
            "http",
            "lan-host",
            8190
        ));
        assertFalse(DownloadSupport.isSameHttpOrigin(
            "http://lan-host:8190/output?token=should-not-leak",
            "http",
            "lan-host",
            8190
        ));
        assertFalse(DownloadSupport.isSameHttpOrigin(
            "blob:http://lan-host:8190/id",
            "http",
            "lan-host",
            8190
        ));
    }
}
