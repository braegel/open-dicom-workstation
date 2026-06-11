"""Core data models shared across the application. Pure data, no Qt."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PacsNode:
    name: str  # display name, e.g. "Main PACS"
    ae_title: str
    host: str
    port: int
    retrieve_method: str = "C-GET"  # "C-GET" or "C-MOVE"


@dataclass(frozen=True)
class StudyQueryResult:
    study_uid: str
    patient_name: str
    patient_id: str
    study_date: str  # raw DICOM DA string, "" if absent
    description: str
    modalities: str  # ModalitiesInStudy joined, e.g. "CT, SR"
    accession_number: str
    num_series: int | None
    num_instances: int | None


@dataclass(frozen=True)
class SeriesQueryResult:
    series_uid: str
    study_uid: str
    modality: str
    series_number: int | None
    description: str
    num_instances: int | None


@dataclass(frozen=True)
class StudyRecord:
    study_uid: str
    patient_name: str
    patient_id: str
    study_date: str
    description: str
    modalities: str


@dataclass(frozen=True)
class SeriesRecord:
    series_uid: str
    study_uid: str
    modality: str
    series_number: int | None
    description: str
    num_instances: int


@dataclass(frozen=True)
class InstanceRecord:
    sop_uid: str
    series_uid: str
    instance_number: int | None
    path: Path  # absolute path of the stored file


@dataclass(frozen=True)
class RetrieveResult:
    completed: int
    failed: int
    warnings: int
    message: str = ""
