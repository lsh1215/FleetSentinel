package io.fleetsentinel.pipeline.model;

import java.io.Serializable;

/**
 * 실패 격리 봉투. {@code schemas/dlq-envelope.avsc} 대응.
 *
 * <p><b>원본 바이트를 무손실로 보존한다.</b> 파싱 실패를 격리하는 곳에서 파싱된 값을
 * 저장하면 자기모순이다.
 */
public final class DlqRecord implements Serializable {

    private static final long serialVersionUID = 1L;

    /** data-design.md §5.4의 4분류. */
    public enum ErrorClass {
        /** 바이트를 스키마로 못 읽었다 */
        PARSE_FAILURE,
        /** 읽었지만 필드가 계약에 안 맞다 */
        SCHEMA_VALIDATION_FAILURE,
        /** 필드는 맞지만 값이 물리적으로 불가능하다(§8.3) */
        BUSINESS_RULE_FAILURE,
        /** 싱크 쓰기가 끝내 실패했다 */
        SINK_WRITE_FAILURE
    }

    private final byte[] originalPayload;
    private final ErrorClass errorClass;
    private final String errorDetail;
    private final String sourceSubscription;
    private final String pipelineStep;
    private final long processingTime;
    private final int attempt;

    public DlqRecord(byte[] originalPayload, ErrorClass errorClass, String errorDetail,
                     String sourceSubscription, String pipelineStep,
                     long processingTime, int attempt) {
        this.originalPayload = originalPayload;
        this.errorClass = errorClass;
        this.errorDetail = errorDetail;
        this.sourceSubscription = sourceSubscription;
        this.pipelineStep = pipelineStep;
        this.processingTime = processingTime;
        this.attempt = attempt;
    }

    public static DlqRecord of(Envelope env, ErrorClass cls, String step, String detail) {
        return new DlqRecord(env.payload(), cls, detail, env.topic(), step,
                System.currentTimeMillis(), 1);
    }

    public byte[] originalPayload() {
        return originalPayload;
    }

    public ErrorClass errorClass() {
        return errorClass;
    }

    public String errorDetail() {
        return errorDetail;
    }

    public String sourceSubscription() {
        return sourceSubscription;
    }

    public String pipelineStep() {
        return pipelineStep;
    }

    public long processingTime() {
        return processingTime;
    }

    public int attempt() {
        return attempt;
    }
}
