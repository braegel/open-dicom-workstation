"""DICOM networking: C-FIND/C-GET/C-MOVE SCUs and the Storage SCP."""


class PacsError(Exception):
    """Base class for PACS networking failures."""


class PacsConnectionError(PacsError):
    """Raised when an association with a PACS node cannot be established."""
