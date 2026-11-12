import hashlib
import json
from pathlib import Path
import sys


def training_signature(definition):
    directory = Path(__file__).resolve().parent
    modules = ("algorithms.py", "datasets.py", "contracts.py", "environment.py", "port_environment.py", "service.py")
    fields = {name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in modules}
    fields.update(python=sys.version, mapping=definition.mapping, timezone=definition.timezone,
                  environment_type=definition.environment_type)
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()
