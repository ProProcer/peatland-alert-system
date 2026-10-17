"""Verified CSV tables for live services on hosts with no working Parquet reader."""
from pathlib import Path
import json

from e_platform.portable_history import ROOT, file_sha, read_portable, value_sha, write_json


class PortableLiveTables:
    history_name = "history.csv.gz"

    def __init__(self, bundle, source_dir):
        self.source_dir = Path(source_dir).resolve()
        self.original, self.provenance = read_portable(Path(bundle))
        handoff = json.loads((ROOT / "b_model/CURRENT_HANDOFF.json").read_text())
        expected = handoff["source_fingerprints"]["history.parquet"]
        if (self.provenance["source_parquet_sha256"] != expected or
                self.source_dir / "history.parquet" != (ROOT / handoff["history"]).resolve() or
                file_sha(self.source_dir / "history.parquet") != expected):
            raise ValueError("Portable live history must match the frozen regional handoff")

    def read(self, directory, columns=None):
        if Path(directory).resolve() == self.source_dir:
            frame = self.original
        else:
            frame, manifest = read_portable(Path(directory))
            if manifest["source_parquet_sha256"] != self.provenance["source_parquet_sha256"]:
                raise ValueError("Live context belongs to a different frozen history")
        return frame[columns] if columns is not None else frame

    def write(self, frame, directory, stem):
        import pandas as pd

        frame = frame.copy(deep=False)
        # Appending pd.NA can turn integer target columns into object arrays.
        # Runtime labels use nullable numeric storage; frozen inputs stay intact.
        for name in ("target_24h", "target_48h", "target_72h"):
            if name in frame:
                frame[name] = pd.to_numeric(frame[name], errors="raise").astype("Float64")
        directory = Path(directory)
        csv = directory / f"{stem}.csv.gz"
        metadata = directory / f"{stem}-manifest.json"
        frame.to_csv(csv, index=False, float_format="%.17g",
                     compression={"method": "gzip", "compresslevel": 1, "mtime": 0})
        manifest = {
            "source_parquet_sha256": self.provenance["source_parquet_sha256"],
            "rows": len(frame), "columns": list(frame),
            "dtypes": {name: str(dtype) for name, dtype in frame.dtypes.items()},
            "csv_gzip_sha256": file_sha(csv), "values_sha256": value_sha(frame),
            "meaning": "Live runtime context; new targets remain null. Not a training export.",
        }
        write_json(metadata, manifest)
        # Verify history before publication, including exact values, nulls and dtypes.
        if stem == "history":
            read_portable(directory)
        return [csv.name, metadata.name]
