"""Factory for synthetic, spec-valid CT DICOM datasets used across the test suite."""

import numpy as np
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid


def make_ct_dataset(
    *,
    study_uid: str | None = None,
    series_uid: str | None = None,
    sop_uid: str | None = None,
    instance_number: int = 1,
    rows: int = 64,
    cols: int = 64,
    pixel_fill: int | np.ndarray = 0,
    window_center: float = 40.0,
    window_width: float = 400.0,
    slope: float = 1.0,
    intercept: float = -1024.0,
    photometric: str = "MONOCHROME2",
    patient_name: str = "DOE^JANE",
    patient_id: str = "PID001",
    study_date: str = "20260101",
    modality: str = "CT",
) -> FileDataset:
    """Build a complete, file-writable synthetic CT dataset."""
    study_uid = study_uid or generate_uid()
    series_uid = series_uid or generate_uid()
    sop_uid = sop_uid or generate_uid()

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = CTImageStorage
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(None, {}, file_meta=file_meta, preamble=b"\x00" * 128)

    ds.SOPClassUID = CTImageStorage
    ds.SOPInstanceUID = sop_uid
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.InstanceNumber = instance_number
    ds.SeriesNumber = 1
    ds.Modality = modality

    ds.PatientName = patient_name
    ds.PatientID = patient_id
    ds.StudyDate = study_date
    ds.StudyTime = "120000"
    ds.AccessionNumber = "ACC001"
    ds.StudyDescription = "SYNTHETIC STUDY"
    ds.SeriesDescription = "SYNTHETIC SERIES"

    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = photometric
    ds.Rows = rows
    ds.Columns = cols
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 1

    ds.RescaleSlope = slope
    ds.RescaleIntercept = intercept
    ds.WindowCenter = window_center
    ds.WindowWidth = window_width

    if isinstance(pixel_fill, np.ndarray):
        pixels = pixel_fill.astype(np.int16, copy=False)
        if pixels.shape != (rows, cols):
            raise ValueError(
                f"pixel_fill shape {pixels.shape} does not match (rows, cols)=({rows}, {cols})"
            )
    else:
        pixels = np.full((rows, cols), pixel_fill, dtype=np.int16)
    ds.PixelData = pixels.tobytes()

    return ds


def make_series(n: int, **kwargs) -> list[FileDataset]:
    """Build *n* instances sharing fresh study/series UIDs, numbered 1..n."""
    study_uid = generate_uid()
    series_uid = generate_uid()
    return [
        make_ct_dataset(
            study_uid=study_uid,
            series_uid=series_uid,
            instance_number=i,
            **kwargs,
        )
        for i in range(1, n + 1)
    ]
