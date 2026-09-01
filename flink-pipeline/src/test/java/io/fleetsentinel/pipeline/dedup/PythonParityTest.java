package io.fleetsentinel.pipeline.dedup;

import static org.assertj.core.api.Assertions.assertThat;

import io.fleetsentinel.pipeline.dedup.SeqWindow.Verdict;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Python {@code SeqDedup}과 Java {@code SeqWindow}가 <b>같은 판정</b>을 내는지 확인한다.
 *
 * <p>같은 알고리즘이 두 언어로 존재하므로(차량은 Python, Flink는 Java) 계약이 갈라지면
 * "재생기에서 검증했다"는 주장이 Flink에 적용되지 않는다. 그래서 무작위 시퀀스 3,000건에
 * 대한 Python 판정을 픽스처로 굳혀두고 Java가 같은 답을 내는지 대조한다.
 *
 * <p>픽스처 재생성은 {@code exploration}에서 한다 — 이 파일 상단 주석 참조.
 */
class PythonParityTest {

    @Test
    @DisplayName("무작위 3,000건에서 Python과 판정이 완전히 일치한다")
    void matchesPython() throws Exception {
        String json = read("/dedup_cross.json");

        int window = Integer.parseInt(scalar(json, "window"));
        List<String[]> seqs = pairs(json);
        List<String> expected = strings(json, "verdicts");
        assertThat(seqs).hasSameSizeAs(expected);

        var w = new SeqWindow(window);
        List<String> mismatches = new ArrayList<>();
        for (int i = 0; i < seqs.size(); i++) {
            Verdict actual = w.accept(seqs.get(i)[0], Long.parseLong(seqs.get(i)[1]));
            if (!actual.name().equals(expected.get(i))) {
                mismatches.add("#%d (boot=%s seq=%s): python=%s java=%s"
                        .formatted(i, seqs.get(i)[0], seqs.get(i)[1], expected.get(i), actual));
                if (mismatches.size() >= 5) {
                    break;
                }
            }
        }
        assertThat(mismatches).as("판정 불일치").isEmpty();

        // 최종 상태도 같아야 한다 — 판정만 같고 상태가 갈리면 다음 레코드부터 어긋난다.
        assertThat(w.lastSeen()).isEqualTo(Long.parseLong(scalar(json, "last_seen")));
        assertThat(w.contiguous()).isEqualTo(Long.parseLong(scalar(json, "contiguous")));
        assertThat(w.lost()).isEqualTo(Long.parseLong(scalar(json, "lost")));
    }

    // ── 최소 JSON 파싱. 테스트 하나 때문에 Jackson을 끌어오지 않는다. ──────

    private static String read(String resource) throws Exception {
        try (InputStream in = PythonParityTest.class.getResourceAsStream(resource)) {
            if (in == null) {
                throw new IllegalStateException("픽스처가 없다: " + resource);
            }
            return new String(in.readAllBytes(), StandardCharsets.UTF_8);
        }
    }

    private static String scalar(String json, String key) {
        Matcher m = Pattern.compile("\"" + key + "\"\\s*:\\s*(-?\\d+)").matcher(json);
        if (!m.find()) {
            throw new IllegalStateException("키 없음: " + key);
        }
        return m.group(1);
    }

    private static List<String[]> pairs(String json) {
        String body = block(json, "seqs");
        List<String[]> out = new ArrayList<>();
        Matcher m = Pattern.compile("\\[\\s*\"([^\"]+)\"\\s*,\\s*(-?\\d+)\\s*]").matcher(body);
        while (m.find()) {
            out.add(new String[]{m.group(1), m.group(2)});
        }
        return out;
    }

    private static List<String> strings(String json, String key) {
        String body = block(json, key);
        List<String> out = new ArrayList<>();
        Matcher m = Pattern.compile("\"([A-Z_]+)\"").matcher(body);
        while (m.find()) {
            out.add(m.group(1));
        }
        return out;
    }

    private static String block(String json, String key) {
        int start = json.indexOf("\"" + key + "\"");
        int open = json.indexOf('[', start);
        int depth = 0;
        for (int i = open; i < json.length(); i++) {
            char c = json.charAt(i);
            if (c == '[') depth++;
            else if (c == ']' && --depth == 0) return json.substring(open, i + 1);
        }
        throw new IllegalStateException("배열이 닫히지 않았다: " + key);
    }
}
