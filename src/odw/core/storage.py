"""Local DICOM store: file layout on disk plus a SQLite index. No Qt imports."""

import sqlite3
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

from pydicom import dcmread
from pydicom.dataset import Dataset

from odw.core.models import InstanceRecord, SeriesRecord, StudyRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
    pk INTEGER PRIMARY KEY,
    patient_id TEXT NOT NULL DEFAULT '',
    patient_name TEXT NOT NULL DEFAULT '',
    birth_date TEXT, sex TEXT,
    UNIQUE (patient_id, patient_name)
);
CREATE TABLE IF NOT EXISTS studies (
    pk INTEGER PRIMARY KEY,
    patient_pk INTEGER NOT NULL REFERENCES patients(pk),
    study_uid TEXT NOT NULL UNIQUE,
    study_date TEXT, study_time TEXT, accession_number TEXT,
    description TEXT, modalities TEXT
);
CREATE TABLE IF NOT EXISTS series (
    pk INTEGER PRIMARY KEY,
    study_pk INTEGER NOT NULL REFERENCES studies(pk),
    series_uid TEXT NOT NULL UNIQUE,
    modality TEXT, series_number INTEGER, description TEXT
);
CREATE TABLE IF NOT EXISTS instances (
    pk INTEGER PRIMARY KEY,
    series_pk INTEGER NOT NULL REFERENCES series(pk),
    sop_uid TEXT NOT NULL UNIQUE,
    sop_class_uid TEXT, instance_number INTEGER,
    rel_path TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_studies_patient ON studies(patient_pk);
CREATE INDEX IF NOT EXISTS idx_series_study ON series(study_pk);
CREATE INDEX IF NOT EXISTS idx_instances_series ON instances(series_pk);
"""


def _opt_int(value: Any) -> int | None:
    return None if value in (None, "") else int(value)


class StorageIndex:
    """SQLite index of the local DICOM store. Thread-safe via thread-local connections."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._local = threading.local()
        self._connections: list[sqlite3.Connection] = []
        self._connections_lock = threading.Lock()
        self._conn().executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, isolation_level=None, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
            with self._connections_lock:
                self._connections.append(conn)
        return conn

    def upsert_instance(self, ds: Dataset, rel_path: str) -> bool:
        """Index *ds* stored at *rel_path*. Return False if the SOP UID is already indexed."""
        conn = self._conn()
        sop_uid = str(ds.SOPInstanceUID)
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute("SELECT pk FROM instances WHERE sop_uid = ?", (sop_uid,)).fetchone()
            if row is not None:
                conn.execute("COMMIT")
                return False

            patient_id = str(ds.get("PatientID", ""))
            patient_name = str(ds.get("PatientName", ""))
            conn.execute(
                "INSERT OR IGNORE INTO patients (patient_id, patient_name, birth_date, sex)"
                " VALUES (?, ?, ?, ?)",
                (
                    patient_id,
                    patient_name,
                    str(ds.get("PatientBirthDate", "")) or None,
                    str(ds.get("PatientSex", "")) or None,
                ),
            )
            (patient_pk,) = conn.execute(
                "SELECT pk FROM patients WHERE patient_id = ? AND patient_name = ?",
                (patient_id, patient_name),
            ).fetchone()

            study_uid = str(ds.StudyInstanceUID)
            conn.execute(
                "INSERT OR IGNORE INTO studies"
                " (patient_pk, study_uid, study_date, study_time, accession_number,"
                "  description, modalities)"
                " VALUES (?, ?, ?, ?, ?, ?, '')",
                (
                    patient_pk,
                    study_uid,
                    str(ds.get("StudyDate", "")),
                    str(ds.get("StudyTime", "")),
                    str(ds.get("AccessionNumber", "")),
                    str(ds.get("StudyDescription", "")),
                ),
            )
            (study_pk,) = conn.execute(
                "SELECT pk FROM studies WHERE study_uid = ?", (study_uid,)
            ).fetchone()

            series_uid = str(ds.SeriesInstanceUID)
            conn.execute(
                "INSERT OR IGNORE INTO series"
                " (study_pk, series_uid, modality, series_number, description)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    study_pk,
                    series_uid,
                    str(ds.get("Modality", "")),
                    _opt_int(ds.get("SeriesNumber")),
                    str(ds.get("SeriesDescription", "")),
                ),
            )
            (series_pk,) = conn.execute(
                "SELECT pk FROM series WHERE series_uid = ?", (series_uid,)
            ).fetchone()

            conn.execute(
                "INSERT INTO instances"
                " (series_pk, sop_uid, sop_class_uid, instance_number, rel_path)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    series_pk,
                    sop_uid,
                    str(ds.get("SOPClassUID", "")),
                    _opt_int(ds.get("InstanceNumber")),
                    rel_path,
                ),
            )

            modalities = ", ".join(
                sorted(
                    {
                        row[0]
                        for row in conn.execute(
                            "SELECT DISTINCT modality FROM series WHERE study_pk = ?",
                            (study_pk,),
                        )
                        if row[0]
                    }
                )
            )
            conn.execute("UPDATE studies SET modalities = ? WHERE pk = ?", (modalities, study_pk))
            conn.execute("COMMIT")
            return True
        except BaseException:
            conn.execute("ROLLBACK")
            raise

    def studies(self) -> list[StudyRecord]:
        rows = self._conn().execute(
            "SELECT s.study_uid, p.patient_name, p.patient_id, s.study_date,"
            "       s.description, s.modalities"
            " FROM studies s JOIN patients p ON p.pk = s.patient_pk"
            " ORDER BY s.study_date DESC"
        )
        return [
            StudyRecord(
                study_uid=r[0],
                patient_name=r[1],
                patient_id=r[2],
                study_date=r[3] or "",
                description=r[4] or "",
                modalities=r[5] or "",
            )
            for r in rows
        ]

    def series_for_study(self, study_uid: str) -> list[SeriesRecord]:
        rows = self._conn().execute(
            "SELECT se.series_uid, st.study_uid, se.modality, se.series_number,"
            "       se.description,"
            "       (SELECT COUNT(*) FROM instances i WHERE i.series_pk = se.pk)"
            " FROM series se JOIN studies st ON st.pk = se.study_pk"
            " WHERE st.study_uid = ?"
            " ORDER BY se.series_number",
            (study_uid,),
        )
        return [
            SeriesRecord(
                series_uid=r[0],
                study_uid=r[1],
                modality=r[2] or "",
                series_number=r[3],
                description=r[4] or "",
                num_instances=r[5],
            )
            for r in rows
        ]

    def instances_for_series(self, series_uid: str) -> list[InstanceRecord]:
        """Return instance records; ``path`` is the *relative* path within the store root."""
        rows = self._conn().execute(
            "SELECT i.sop_uid, se.series_uid, i.instance_number, i.rel_path"
            " FROM instances i JOIN series se ON se.pk = i.series_pk"
            " WHERE se.series_uid = ?"
            " ORDER BY i.instance_number",
            (series_uid,),
        )
        return [
            InstanceRecord(sop_uid=r[0], series_uid=r[1], instance_number=r[2], path=Path(r[3]))
            for r in rows
        ]

    def close(self) -> None:
        with self._connections_lock:
            for conn in self._connections:
                conn.close()
            self._connections.clear()
        self._local = threading.local()


class DicomStore:
    """File-backed DICOM store with layout <root>/<study_uid>/<series_uid>/<sop_uid>.dcm."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._index = StorageIndex(self._root / "index.db")

    def ingest(self, ds: Dataset) -> InstanceRecord:
        """Write *ds* into the store and index it. Idempotent on duplicate SOP UID."""
        rel_path = f"{ds.StudyInstanceUID}/{ds.SeriesInstanceUID}/{ds.SOPInstanceUID}.dcm"
        abs_path = self._root / rel_path
        inserted = self._index.upsert_instance(ds, rel_path)
        if inserted:
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            ds.save_as(abs_path, enforce_file_format=True)
        return InstanceRecord(
            sop_uid=str(ds.SOPInstanceUID),
            series_uid=str(ds.SeriesInstanceUID),
            instance_number=_opt_int(ds.get("InstanceNumber")),
            path=abs_path,
        )

    def studies(self) -> list[StudyRecord]:
        return self._index.studies()

    def series_for_study(self, study_uid: str) -> list[SeriesRecord]:
        return self._index.series_for_study(study_uid)

    def instances_for_series(self, series_uid: str) -> list[InstanceRecord]:
        return [
            replace(rec, path=self._root / rec.path)
            for rec in self._index.instances_for_series(series_uid)
        ]

    def load_series_datasets(self, series_uid: str) -> list[Dataset]:
        return [dcmread(rec.path) for rec in self.instances_for_series(series_uid)]

    def close(self) -> None:
        self._index.close()
