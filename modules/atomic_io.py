"""
Escrita atomica de arquivos JSON.

Grava em arquivo temporario no MESMO diretorio, faz fsync e os.replace.
Um corte de energia no meio da gravacao nunca deixa o arquivo destino
truncado — ou fica a versao antiga, ou a nova completa.
"""

import json
import os
import tempfile


def atomic_write_json(path, data, indent: int = 2) -> None:
    """
    Grava `data` como JSON em `path` de forma atomica.

    Args:
        path: Caminho de destino (str ou Path).
        data: Objeto serializavel em JSON.
        indent: Indentacao do JSON.
    """
    path = str(path)
    dir_name = os.path.dirname(path) or "."
    os.makedirs(dir_name, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=dir_name, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
