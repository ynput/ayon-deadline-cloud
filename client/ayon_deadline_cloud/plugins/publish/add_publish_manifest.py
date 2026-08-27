"""Write the AYON publish manifest and attach it to the job.

Instead of interpolating a growing list of AYON context values into the
publish step script, the submitter serializes a single versioned manifest
and ships it to the worker as a job attachment. The publish step then only
needs to know where that file is.

"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import pyblish.api
from ayon_core.pipeline.publish import PublishError
from ayon_deadline_cloud.api.datatypes import (
    PUBLISH_MANIFEST_FILENAME,
    PublishContextData,
    PublishManifest,
)

if TYPE_CHECKING:
    from logging import Logger

PUBLISH_DATA_PARAM_NAME = "ayonPublishData"


class AddPublishManifest(pyblish.api.InstancePlugin):
    """Serialize publish manifest and add it to the job attachments."""

    label = "Add AYON Publish Manifest to the Job"
    # before the publish step is built and before submission
    order = pyblish.api.IntegratorOrder - 0.01
    targets: ClassVar[list[str]] = ["local"]  # ty: ignore[invalid-attribute-override]
    families: ClassVar[list[str]] = ["deadline_cloud"]  # ty: ignore[invalid-attribute-override]
    log: Logger

    def process(self, instance: pyblish.api.Instance) -> None:
        """Write the manifest and register it with the job template.

        Args:
            instance: Pyblish instance with collected job data.

        Raises:
            PublishError: When job data has not been collected.

        """
        job_data = instance.data.get("deadline_cloud_job_data")
        if not job_data:
            msg = (
                "No Deadline Cloud job data collected, cannot build "
                "publish manifest."
            )
            raise PublishError(msg)

        job_template: dict[str, Any] = job_data["jobTemplate"]
        manifest = self._build_manifest(instance, job_template)

        staging_dir = Path(tempfile.mkdtemp(prefix="ayon_dc_publish_"))
        manifest_path = manifest.write(
            staging_dir / PUBLISH_MANIFEST_FILENAME
        )
        self.log.debug("Publish manifest written to: %s", manifest_path)

        instance.context.data.setdefault("cleanupFullPaths", []).append(
            manifest_path.as_posix()
        )

        self._register_parameter(job_data, manifest_path)
        self._register_asset_reference(job_data, manifest_path)

        instance.data["deadline_cloud_publish_manifest"] = manifest

    @staticmethod
    def _build_manifest(
        instance: pyblish.api.Instance,
        job_template: dict[str, Any],
    ) -> PublishManifest:
        """Collect AYON context into a manifest.

        Args:
            instance: Pyblish instance.
            job_template: Job template with collected parameter defaults.

        Returns:
            PublishManifest: Manifest ready to be serialized.

        """
        context = instance.context
        output_path = next(
            (
                param.get("default", "")
                for param in job_template.get("parameterDefinitions", [])
                if param.get("name") == "OutputFilePath"
            ),
            "",
        )

        return PublishManifest(
            context=PublishContextData(
                projectName=context.data["projectName"],
                folderPath=instance.data["folderPath"],
                userName=context.data["user"],
                productBaseType=instance.data.get("productBaseType", ""),
                variant=instance.data.get("variant", ""),
                taskName=instance.data.get("task"),
                hostName=context.data.get("hostName"),
                sourceFile=context.data.get("currentFile", ""),
                outputPath=output_path,
            )
        )

    @staticmethod
    def _register_parameter(
        job_data: dict[str, Any],
        manifest_path: Path,
    ) -> None:
        """Declare and value the manifest job parameter.

        Declaring it as ``PATH``/``dataFlow: IN`` is what makes Deadline
        Cloud upload the file and remap the value on the worker.

        Args:
            job_data: Collected Deadline Cloud job data.
            manifest_path: Path of the written manifest.

        """
        job_template: dict[str, Any] = job_data["jobTemplate"]
        param_defs: list[dict] = job_template.setdefault(
            "parameterDefinitions", []
        )
        if not any(
            param.get("name") == PUBLISH_DATA_PARAM_NAME
            for param in param_defs
        ):
            param_defs.append({
                "name": PUBLISH_DATA_PARAM_NAME,
                "type": "PATH",
                "objectType": "FILE",
                "dataFlow": "IN",
                "description": "AYON publish manifest for this job",
                "userInterface": {"control": "HIDDEN"},
            })

        parameter_values: list[dict] = job_data["parameterValues"]
        value = manifest_path.as_posix()
        for parameter_value in parameter_values:
            if parameter_value.get("name") == PUBLISH_DATA_PARAM_NAME:
                parameter_value["value"] = value
                break
        else:
            parameter_values.append(
                {"name": PUBLISH_DATA_PARAM_NAME, "value": value}
            )

    @staticmethod
    def _register_asset_reference(
        job_data: dict[str, Any],
        manifest_path: Path,
    ) -> None:
        """Add the manifest to the job input attachments.

        Args:
            job_data: Collected Deadline Cloud job data.
            manifest_path: Path of the written manifest.

        """
        filenames: list[str] = (
            job_data["assetReferences"]["assetReferences"]
            .setdefault("inputs", {})
            .setdefault("filenames", [])
        )
        value = manifest_path.as_posix()
        if value not in filenames:
            filenames.append(value)
