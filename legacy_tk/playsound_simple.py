# playsound_simple.py
"""Simple cross‑platform sound playback module.

Provides a single function :func:`play_sound` that plays an audio file (WAV, MP3, etc.)
without requiring any third‑party Python packages.

The implementation uses the built‑in ``winsound`` module on Windows and the
system ``afplay`` (macOS) or ``aplay`` / ``paplay`` (Linux) utilities via
``subprocess``. These utilities are typically present on the respective
platforms. If none of the utilities are available, a ``RuntimeError`` is
raised.

Example
-------
```python
from playsound_simple import play_sound

play_sound('example.wav')
```
"""

import os
import platform
import subprocess
from typing import List


def _is_executable_available(executable: str) -> bool:
    """Return ``True`` if *executable* can be found on the ``PATH``.

    ``subprocess`` will raise ``FileNotFoundError`` when trying to run a
    non‑existent command, but checking ahead gives a clearer error message.
    """
    return any(
        os.access(os.path.join(path, executable), os.X_OK)
        for path in os.environ.get("PATH", "").split(os.pathsep)
    )


def play_sound(file_path: str, *, block: bool = False) -> None:
    """Play an audio file.

    Parameters
    ----------
    file_path: str
        Path to the audio file to play. The file must exist.
    block: bool, default ``False``
        If ``True`` the call blocks until playback finishes. When ``False``
        the sound plays asynchronously (the default behaviour matches the
        original *playsound* library).

    Raises
    ------
    FileNotFoundError
        If *file_path* does not exist.
    RuntimeError
        If the platform is unsupported or none of the required playback
        utilities are available.
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Audio file not found: {file_path}")

    system = platform.system()
    # Windows – use winsound
    if system == "Windows":
        import winsound
        flags = winsound.SND_FILENAME
        if not block:
            flags |= winsound.SND_ASYNC
        winsound.PlaySound(file_path, flags)
        return

    # macOS – use afplay (bundled with the OS)
    if system == "Darwin":
        if not _is_executable_available("afplay"):
            raise RuntimeError("The 'afplay' utility is required on macOS but was not found.")
        cmd = ["afplay", file_path]
        if not block:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return

    # Linux – try paplay (PulseAudio) then aplay (ALSA)
    if system == "Linux":
        if _is_executable_available("paplay"):
            cmd = ["paplay", file_path]
        elif _is_executable_available("aplay"):
            cmd = ["aplay", file_path]
        else:
            raise RuntimeError(
                "Neither 'paplay' nor 'aplay' was found on this Linux system."
            )
        if not block:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return

    # If we reach here the OS is not recognized.
    raise RuntimeError(f"Unsupported platform: {system}")


def __all__() -> List[str]:
    """Exported symbols for ``from playsound_simple import *``."""
    return ["play_sound"]
