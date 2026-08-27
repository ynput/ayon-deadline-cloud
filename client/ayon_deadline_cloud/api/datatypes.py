"""Data classes."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union

if TYPE_CHECKING:
    from ayon_core.pipeline.traits import Representation as TraitRepresentation

# Bump whenever the manifest layout changes in a way older readers
# cannot handle. Submitter and farm side may run different addon versions.
PUBLISH_MANIFEST_SCHEMA_VERSION = 1
PUBLISH_MANIFEST_FILENAME = "ayon_publish_manifest.json"


class UnsupportedManifestVersionError(Exception):
    """Raised when a publish manifest cannot be read by this addon."""

    def __init__(self, version: int) -> None:
        """Constructor.

        Args:
            version: Schema version found in the manifest.

        """
        self.version = version
        super().__init__(
            f"Unsupported publish manifest schema version '{version}', "
            f"expected '{PUBLISH_MANIFEST_SCHEMA_VERSION}'."
        )


@dataclass
class StandardRepresentation:
    """Representation dataclass."""
    name: str
    ext: str
    files: Union[str, list[str]]
    stagingDir: str
    tags: list[str]


@dataclass
class InstanceData:
    """Instance dataclass."""
    publish: bool
    active: bool
    label: str
    name: str
    productName: str
    productBaseType: str
    productType: str
    family: str
    families: list[str]
    folderPath: str
    task: str
    variant: str
    standard_representations: list[StandardRepresentation]
    trait_representations: list[TraitRepresentation]


@dataclass
class PublishContextData:
    """AYON context handed over to the farm publishing process."""
    projectName: str
    folderPath: str
    userName: str
    productBaseType: str
    variant: str
    taskName: Optional[str] = None
    hostName: Optional[str] = None
    sourceFile: Optional[str] = None
    outputPath: Optional[str] = None


@dataclass
class PublishManifest:
    """Versioned payload exchanged between submitter and publish job.

    Serialized next to the job bundle and shipped to the worker as a job
    attachment, replacing the ad-hoc set of CLI flags previously
    interpolated into the publish step script.

    Note that paths stored inside the manifest are *not* remapped by
    Deadline Cloud - only the manifest location itself is. Callers must
    apply the session path mapping rules to any path they read from here.
    """
    context: PublishContextData
    schemaVersion: int = PUBLISH_MANIFEST_SCHEMA_VERSION
    # Reserved for submitter-computed instances so the farm side does not
    # have to re-derive them by scanning the output directory.
    instances: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return the manifest as a plain JSON-serializable dict.

        Returns:
            dict[str, Any]: Serialized manifest.

        """
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PublishManifest:
        """Construct a manifest from its serialized form.

        Args:
            data: Deserialized manifest content.

        Returns:
            PublishManifest: Parsed manifest.

        Raises:
            UnsupportedManifestVersionError: When the schema version is
                not supported by this addon version.

        """
        version = int(data.get("schemaVersion", 0))
        if version != PUBLISH_MANIFEST_SCHEMA_VERSION:
            raise UnsupportedManifestVersionError(version)

        known_keys = {f.name for f in fields(PublishContextData)}
        context_data = {
            key: value
            for key, value in (data.get("context") or {}).items()
            if key in known_keys
        }
        return cls(
            context=PublishContextData(**context_data),
            schemaVersion=version,
            instances=list(data.get("instances") or []),
        )

    def write(self, path: Union[str, Path]) -> Path:
        """Serialize the manifest to ``path``.

        Args:
            path: Destination file path.

        Returns:
            Path: Path the manifest was written to.

        """
        manifest_path = Path(path)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with manifest_path.open("w", encoding="utf-8") as stream:
            json.dump(self.to_dict(), stream, indent=4)
        return manifest_path

    @classmethod
    def from_file(cls, path: Union[str, Path]) -> PublishManifest:
        """Read a manifest from ``path``.

        Args:
            path: Manifest file path.

        Returns:
            PublishManifest: Parsed manifest.

        """
        with Path(path).open(encoding="utf-8") as stream:
            return cls.from_dict(json.load(stream))
