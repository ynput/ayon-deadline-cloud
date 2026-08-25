"""Deadline Cloud Addon for AYON."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, cast

import click
from ayon_core.addon import AYONAddon, IPluginPaths, click_wrap

from ayon_deadline_cloud.api.datatypes import PublishManifest
from ayon_deadline_cloud.api.publish import publish_content

from .version import __version__

if TYPE_CHECKING:
    from logging import Logger

DEADLINE_CLOUD_ADDON_ROOT = os.path.dirname(os.path.abspath(__file__))


class DeadlineCloudAddon(AYONAddon, IPluginPaths):
    """Deadline Cloud Addon for AYON."""
    name = "deadline_cloud"
    version = __version__
    log: Logger  # type: ignore[assignment]

    @staticmethod
    def add_implementation_envs(
        env: dict[str, str], _app: Any) -> None:  # ruff: ignore[any-type]
        """Add environment variables for the addon implementation.

        Args:
            env: Dictionary of environment variables to be updated with
                implementation specific variables.
            _app: Name of the host application to add specific environment
                variables for.

        """
        # TODO(antirotor): Implement this env variable to set AYON scoped
        # Deadline Cloud configuration file path for the client to use.
        # env["DEADLINE_CONFIG_FILE_PATH"] = ...

    def get_publish_plugin_paths(  # ruff: ignore[no-self-use]
            self,
            host_name: str,
    ) -> list[str]:
        """Return list of paths to publish plugins.

        Args:
            host_name: Optional name of the host application
                to get specific plugin paths.

        Returns:
            List of paths to publish plugins.

        """
        return [os.path.join(
            DEADLINE_CLOUD_ADDON_ROOT, "plugins", "publish")]

    def get_create_plugin_paths(  # ruff: ignore[no-self-use]
            self,
            host_name: str,
    ) -> list[str]:
        """Return list of paths to creator plugins.

        Args:
            host_name: Optional name of the host application
                to get specific plugin paths.

        Returns:
            List of paths to creator plugins.

        """
        return [os.path.join(
            DEADLINE_CLOUD_ADDON_ROOT,
            "plugins", "create", host_name or "global")]

    def _publish(
            self,
            path: Optional[str],
            path_mapping_file: Optional[str],
            publish_data: Optional[str] = None,
    ) -> None:
        """Publish the result of a Deadline Cloud processed job.

        Values are primarily taken from the publish manifest
        (``--publish-data``). The individual options are deprecated
        overrides kept for jobs submitted by older addon versions.

        Args:
            path: Path to the folder containing the job
                result to publish.
            path_mapping_file: Optional path to a file containing path mapping
                rules, which can be used to resolve file paths during
                the publishing process.
            publish_data: Path to the AYON publish manifest shipped with
                the job as an attachment.

        Raises:
            ValueError: When required publishing context cannot be resolved.

        """
        manifest: Optional[PublishManifest] = None
        if publish_data:
            manifest = PublishManifest.from_file(publish_data)
            self.log.debug(
                "loaded publish manifest v%s from: %s",
                manifest.schemaVersion, publish_data
            )
            ctx = manifest.context
            path = path or ctx.outputPath
            folder_path = ctx.folderPath
            project_name = ctx.projectName
            user_name = ctx.userName
            product_base_type = ctx.productBaseType
            variant = ctx.variant
            task_name = ctx.taskName
            host_name = ctx.hostName
            source_file = ctx.sourceFile
        else:
            self.log.warning(
                "No publish manifest provided, falling back to deprecated "
                "individual CLI options."
            )

        self.log.debug(
            "publish called with arguments: "
            "folder_path=%s, project_name=%s, "
            "user_name=%s, product_base_name=%s, task_name=%s, "
            "host_name=%s, source_file=%s, variant=%s",
            folder_path, project_name, user_name,
            product_base_type, task_name, host_name, source_file,
            variant
        )

        missing = [
            name
            for name, value in (
                ("path", path),
                ("folder-path", folder_path),
                ("project-name", project_name),
                ("user-name", user_name),
                ("product-base-type", product_base_type),
                ("variant", variant),
            )
            if not value
        ]
        if missing:
            msg = (
                "Missing required publishing context: "
                f"{', '.join(missing)}"
            )
            raise ValueError(msg)

        path = cast("str", path)

        # This is simple remapping code to take the path specified in the job
        # and remap it to current system. Deadline Cloud won't do it
        # automatically, because the path isn't of PATH type (it can't be
        # because of the restriction in OpenJD that paths must be relative
        # to the job bundle. This remapping is very basic and is based on
        # simple string replacement - we need to eventually replace it with
        # something more robust, or force somehow Deadline Cloud to do it.

        if path_mapping_file:
            self.log.debug("Using path mapping file: %s", path_mapping_file)
            with open(path_mapping_file, encoding="utf8") as f:
                path_mapping = json.load(f)

            for rules in path_mapping["path_mapping_rules"]:
                if path.startswith(rules["source_path"]):
                    path = path.replace(
                        rules["source_path"],
                        f'{rules["destination_path"]}{os.path.sep}',
                        1
                    )
                    if os.path.sep == "/":
                        path = path.replace("\\", "/")

                    path = Path(path).resolve().as_posix()
                    self.log.debug(
                        "Mapped path to: %s using rules: %s",
                        path, rules
                    )
                    break

        publish_content(
            path=path,
            project_name=project_name,
            folder_path=folder_path,
            product_base_type=product_base_type,
            variant=variant,
            user_name=user_name,
            task_name=task_name,
            host_name=host_name,
            source_file=source_file,
        )

    def _cli_main(self) -> None:
        """Add CLI commands to this addon."""

    def cli(self, addon_click_group: click.Group) -> None:
        """CLI interface.

        Args:
            addon_click_group: Click group to add commands to.

        """
        cli_main = click_wrap.group(
            self._cli_main,
            name=self.name,
            help="Deadline Cloud commands",
        )

        cli_main.command(
            self._publish,
            name="publish",
            help=(
                "Publish the result of a Deadline Cloud "
                "processed job."
            ),
        ).option(
            "--publish-data",
            type=click.Path(exists=True, file_okay=True, dir_okay=False),
            required=False,
            help="Path to the AYON publish manifest.",
        ).option(
            "--path-mapping-file",
            type=click.Path(exists=True, file_okay=True, dir_okay=False),
            required=False,
        ).argument(
            "path",
            nargs=1,
            required=False,
            type=click.Path(exists=False, file_okay=False, dir_okay=True),
        )

        addon_click_group.add_command(cli_main.to_click_obj())
