"""OSChaff — a difficulty dial for OSWorld 2.0.

Inject controlled information-noise (distractor emails / chat messages) into an
OSWorld 2.0 task without altering ground truth, producing a harder fork you can
run with the stock OSWorld-V2 runner.

CLI:  python -m oschaff.chaff <task_id> --group <id> --volume 0-10 --deceptiveness 0-10
"""

from .config import ChaffConfig

__all__ = ["ChaffConfig"]
__version__ = "0.2.0"
