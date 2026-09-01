from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class RecordKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    RECORD_KIND_UNSPECIFIED: _ClassVar[RecordKind]
    RECORD_KIND_SIGNAL: _ClassVar[RecordKind]
    RECORD_KIND_SEGMENT_REF: _ClassVar[RecordKind]
    RECORD_KIND_PERCEPTION: _ClassVar[RecordKind]
RECORD_KIND_UNSPECIFIED: RecordKind
RECORD_KIND_SIGNAL: RecordKind
RECORD_KIND_SEGMENT_REF: RecordKind
RECORD_KIND_PERCEPTION: RecordKind

class IngestRecord(_message.Message):
    __slots__ = ("seq", "kind", "payload")
    SEQ_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_FIELD_NUMBER: _ClassVar[int]
    seq: int
    kind: RecordKind
    payload: bytes
    def __init__(self, seq: _Optional[int] = ..., kind: _Optional[_Union[RecordKind, str]] = ..., payload: _Optional[bytes] = ...) -> None: ...

class Ack(_message.Message):
    __slots__ = ("ack_seq",)
    ACK_SEQ_FIELD_NUMBER: _ClassVar[int]
    ack_seq: int
    def __init__(self, ack_seq: _Optional[int] = ...) -> None: ...

class BeginUploadRequest(_message.Message):
    __slots__ = ("t_start_us", "t_end_us", "size_bytes", "sha256", "part_size_bytes", "scene_id", "sensor_channels", "sample_count")
    T_START_US_FIELD_NUMBER: _ClassVar[int]
    T_END_US_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    SHA256_FIELD_NUMBER: _ClassVar[int]
    PART_SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    SCENE_ID_FIELD_NUMBER: _ClassVar[int]
    SENSOR_CHANNELS_FIELD_NUMBER: _ClassVar[int]
    SAMPLE_COUNT_FIELD_NUMBER: _ClassVar[int]
    t_start_us: int
    t_end_us: int
    size_bytes: int
    sha256: str
    part_size_bytes: int
    scene_id: str
    sensor_channels: _containers.RepeatedScalarFieldContainer[str]
    sample_count: int
    def __init__(self, t_start_us: _Optional[int] = ..., t_end_us: _Optional[int] = ..., size_bytes: _Optional[int] = ..., sha256: _Optional[str] = ..., part_size_bytes: _Optional[int] = ..., scene_id: _Optional[str] = ..., sensor_channels: _Optional[_Iterable[str]] = ..., sample_count: _Optional[int] = ...) -> None: ...

class BeginUploadResponse(_message.Message):
    __slots__ = ("segment_id", "upload_id", "blob_uri", "part_urls", "expires_at_us")
    SEGMENT_ID_FIELD_NUMBER: _ClassVar[int]
    UPLOAD_ID_FIELD_NUMBER: _ClassVar[int]
    BLOB_URI_FIELD_NUMBER: _ClassVar[int]
    PART_URLS_FIELD_NUMBER: _ClassVar[int]
    EXPIRES_AT_US_FIELD_NUMBER: _ClassVar[int]
    segment_id: str
    upload_id: str
    blob_uri: str
    part_urls: _containers.RepeatedCompositeFieldContainer[PartUrl]
    expires_at_us: int
    def __init__(self, segment_id: _Optional[str] = ..., upload_id: _Optional[str] = ..., blob_uri: _Optional[str] = ..., part_urls: _Optional[_Iterable[_Union[PartUrl, _Mapping]]] = ..., expires_at_us: _Optional[int] = ...) -> None: ...

class PartUrl(_message.Message):
    __slots__ = ("part_number", "url")
    PART_NUMBER_FIELD_NUMBER: _ClassVar[int]
    URL_FIELD_NUMBER: _ClassVar[int]
    part_number: int
    url: str
    def __init__(self, part_number: _Optional[int] = ..., url: _Optional[str] = ...) -> None: ...

class CompleteUploadRequest(_message.Message):
    __slots__ = ("segment_id", "upload_id", "parts", "t_start_us")
    SEGMENT_ID_FIELD_NUMBER: _ClassVar[int]
    UPLOAD_ID_FIELD_NUMBER: _ClassVar[int]
    PARTS_FIELD_NUMBER: _ClassVar[int]
    T_START_US_FIELD_NUMBER: _ClassVar[int]
    segment_id: str
    upload_id: str
    parts: _containers.RepeatedCompositeFieldContainer[PartEtag]
    t_start_us: int
    def __init__(self, segment_id: _Optional[str] = ..., upload_id: _Optional[str] = ..., parts: _Optional[_Iterable[_Union[PartEtag, _Mapping]]] = ..., t_start_us: _Optional[int] = ...) -> None: ...

class PartEtag(_message.Message):
    __slots__ = ("part_number", "etag")
    PART_NUMBER_FIELD_NUMBER: _ClassVar[int]
    ETAG_FIELD_NUMBER: _ClassVar[int]
    part_number: int
    etag: str
    def __init__(self, part_number: _Optional[int] = ..., etag: _Optional[str] = ...) -> None: ...

class CompleteUploadResponse(_message.Message):
    __slots__ = ("blob_uri", "size_bytes", "verified")
    BLOB_URI_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    VERIFIED_FIELD_NUMBER: _ClassVar[int]
    blob_uri: str
    size_bytes: int
    verified: bool
    def __init__(self, blob_uri: _Optional[str] = ..., size_bytes: _Optional[int] = ..., verified: _Optional[bool] = ...) -> None: ...

class RefreshUrlsRequest(_message.Message):
    __slots__ = ("segment_id", "upload_id", "part_numbers", "t_start_us")
    SEGMENT_ID_FIELD_NUMBER: _ClassVar[int]
    UPLOAD_ID_FIELD_NUMBER: _ClassVar[int]
    PART_NUMBERS_FIELD_NUMBER: _ClassVar[int]
    T_START_US_FIELD_NUMBER: _ClassVar[int]
    segment_id: str
    upload_id: str
    part_numbers: _containers.RepeatedScalarFieldContainer[int]
    t_start_us: int
    def __init__(self, segment_id: _Optional[str] = ..., upload_id: _Optional[str] = ..., part_numbers: _Optional[_Iterable[int]] = ..., t_start_us: _Optional[int] = ...) -> None: ...

class AbortUploadRequest(_message.Message):
    __slots__ = ("segment_id", "upload_id", "t_start_us")
    SEGMENT_ID_FIELD_NUMBER: _ClassVar[int]
    UPLOAD_ID_FIELD_NUMBER: _ClassVar[int]
    T_START_US_FIELD_NUMBER: _ClassVar[int]
    segment_id: str
    upload_id: str
    t_start_us: int
    def __init__(self, segment_id: _Optional[str] = ..., upload_id: _Optional[str] = ..., t_start_us: _Optional[int] = ...) -> None: ...

class AbortUploadResponse(_message.Message):
    __slots__ = ("aborted",)
    ABORTED_FIELD_NUMBER: _ClassVar[int]
    aborted: bool
    def __init__(self, aborted: _Optional[bool] = ...) -> None: ...
