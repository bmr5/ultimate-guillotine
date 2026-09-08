import logging
import os
import subprocess
from pathlib import Path

from ultimate_guillotine.config import Settings

log = logging.getLogger(__name__)


class HermesNotifier:
    def __init__(
        self,
        profile_home: str,
        runner=subprocess.run,
        channels: dict[str, str] | None = None,
    ) -> None:
        self._home = str(Path(profile_home).expanduser())
        self._runner = runner
        self._channels = channels or {}

    @classmethod
    def from_settings(cls, settings: Settings, runner=subprocess.run) -> "HermesNotifier":
        return cls(settings.hermes_profile_home, runner, {
            "ops": settings.discord_ops_channel,
            "feed": settings.discord_feed_channel,
            "drafts": settings.discord_drafts_channel,
            "alerts": settings.discord_alerts_channel,
        })

    def send(self, channel: str, text: str) -> bool:
        env = {**os.environ, "HERMES_HOME": self._home}
        try:
            result = self._runner(
                ["hermes", "send", "--to", f"discord:{channel}", "--quiet", text],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                log.warning("hermes send to %s failed with code %s", channel, result.returncode)
                return False
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("hermes send to %s raised %s", channel, exc.__class__.__name__)
            return False

    def ops(self, text: str) -> bool:
        return self.send(self._channels["ops"], text)

    def feed(self, text: str) -> bool:
        return self.send(self._channels["feed"], text)

    def drafts(self, text: str) -> bool:
        return self.send(self._channels["drafts"], text)

    def alerts(self, text: str) -> bool:
        return self.send(self._channels["alerts"], text)
