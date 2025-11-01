import re
from typing import Any

DURATION_PATTERN = r"^\d+(\.\d{1,9})?s$"

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .gemini_enums import Source, State


class Status(BaseModel):
    code: int = Field(description="The status code, which should be an enum value of `google.rpc.Code`.")
    message: str = Field(
        description="A developer-facing error message, which should be in English. Any user-facing error message should be localized and sent in the `google.rpc.Status.details` field, or localized by the client."
    )
    details: list[dict[str, Any]] | None = Field(
        default=None,
        description="A list of messages that carry the error details. There is a common set of message types for APIs to use.",
    )

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("details")
    @classmethod
    def validate_details(cls, v: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        for idx, item in enumerate(v):
            if not isinstance(item, dict) or "@type" not in item:
                raise ValueError(f"Item at index {idx} in details must be a dict with a '@type' key, got: {item}")
        return v


class VideoFileMetadata(BaseModel):
    video_duration: str | None = Field(
        default=None,
        alias="videoDuration",
        description="Duration of the video. A duration in seconds with up to nine fractional digits, ending with 's'. Example: '3.5s'.",
    )

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("video_duration")
    @classmethod
    def validate_video_duration(cls, v: str | None) -> str | None:
        if v is not None and not re.match(DURATION_PATTERN, v):
            raise ValueError("Invalid duration format")
        return v


class File(BaseModel):
    name: str = Field(
        description='Immutable. Identifier. The `File` resource name. The ID (name excluding the "files/" prefix) can contain up to 40 characters that are lowercase alphanumeric or dashes (-). The ID cannot start or end with a dash. If the name is empty on create, a unique name will be generated. Example: `files/123-456`'
    )
    display_name: str | None = Field(
        default=None,
        alias="displayName",
        description='Optional. The human-readable display name for the `File`. The display name must be no more than 512 characters in length, including spaces. Example: "Welcome Image"',
    )
    mime_type: str = Field(alias="mimeType", description="Output only. MIME type of the file.")
    size_bytes: str = Field(alias="sizeBytes", description="Output only. Size of the file in bytes.")
    create_time: str = Field(
        alias="createTime",
        description='Output only. The timestamp of when the `File` was created.Uses RFC 3339, where generated output will always be Z-normalized and uses 0, 3, 6 or 9 fractional digits. Offsets other than "Z" are also accepted. Examples: `"2014-10-02T15:01:23Z"`, `"2014-10-02T15:01:23.045123456Z"` or `"2014-10-02T15:01:23+05:30"`.',
    )
    update_time: str = Field(
        alias="updateTime",
        description='Output only. The timestamp of when the `File` was last updated.Uses RFC 3339, where generated output will always be Z-normalized and uses 0, 3, 6 or 9 fractional digits. Offsets other than "Z" are also accepted. Examples: `"2014-10-02T15:01:23Z"`, `"2014-10-02T15:01:23.045123456Z"` or `"2014-10-02T15:01:23+05:30"`.',
    )
    expiration_time: str | None = Field(
        default=None,
        alias="expirationTime",
        description='Output only. The timestamp of when the `File` will be deleted. Only set if the `File` is scheduled to expire.Uses RFC 3339, where generated output will always be Z-normalized and uses 0, 3, 6 or 9 fractional digits. Offsets other than "Z" are also accepted. Examples: `"2014-10-02T15:01:23Z"`, `"2014-10-02T15:01:23.045123456Z"` or `"2014-10-02T15:01:23+05:30"`.',
    )
    sha256_hash: str = Field(
        alias="sha256Hash", description="Output only. SHA-256 hash of the uploaded bytes.A base64-encoded string."
    )
    uri: str = Field(description="Output only. The uri of the `File`.")
    download_uri: str = Field(alias="downloadUri", description="Output only. The download uri of the `File`.")
    state: State = Field(description="Output only. Processing state of the File.")
    source: Source = Field(description="Source of the File.")
    error: Status | None = Field(default=None, description="Output only. Error status if File processing failed.")
    video_metadata: VideoFileMetadata | None = Field(
        default=None, alias="videoMetadata", description="Output only. Metadata for a video."
    )

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("size_bytes")
    @classmethod
    def validate_size_bytes(cls, v: str) -> str:
        try:
            int(v)
        except ValueError:
            raise ValueError(f"'size_bytes' must be a string representing a numeric file size in bytes, but got '{v}'")
        return v
