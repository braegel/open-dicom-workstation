"""Catalog of transfer syntaxes the workstation can offer and accept. Pure data, no Qt."""

from pydicom.uid import (
    JPEG2000,
    DeflatedExplicitVRLittleEndian,
    ExplicitVRLittleEndian,
    ImplicitVRLittleEndian,
    JPEG2000Lossless,
    JPEGBaseline8Bit,
    JPEGLosslessSV1,
    JPEGLSLossless,
    RLELossless,
)

#: Ordered catalog of supported transfer syntaxes: UID -> human-readable name.
TRANSFER_SYNTAXES: dict[str, str] = {
    str(ExplicitVRLittleEndian): "Explicit VR Little Endian",
    str(ImplicitVRLittleEndian): "Implicit VR Little Endian",
    str(DeflatedExplicitVRLittleEndian): "Deflated Explicit VR Little Endian",
    str(RLELossless): "RLE Lossless",
    str(JPEGBaseline8Bit): "JPEG Baseline (Process 1)",
    str(JPEGLosslessSV1): "JPEG Lossless SV1",
    str(JPEGLSLossless): "JPEG-LS Lossless",
    str(JPEG2000Lossless): "JPEG 2000 Lossless",
    str(JPEG2000): "JPEG 2000",
}

#: Transfer syntaxes offered/accepted when nothing else is configured.
DEFAULT_TRANSFER_SYNTAXES: list[str] = [
    str(ExplicitVRLittleEndian),
    str(ImplicitVRLittleEndian),
]
