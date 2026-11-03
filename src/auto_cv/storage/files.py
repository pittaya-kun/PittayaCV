# -*- coding: utf-8 -*-
"""
Auto-CV - File Storage Helpers Module
Version: 1.0.0
Author: Pittaya
License: MIT
Description: YAML/JSON serialization, atomic writes, backups, directory management.
"""

import json
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from datetime import datetime
from dataclasses import dataclass

import yaml

from auto_cv.config import get_settings


# ============================================================
# DATA TYPES (SRP - tipos de retorno estruturados)
# ============================================================

@dataclass
class FileInfo:
    """Metadados de arquivo."""
    path: Path
    name: str
    size: int
    modified: datetime
    extension: str

    @property
    def size_human(self) -> str:
        """Tamanho legível (KB, MB)."""
        for unit in ["B", "KB", "MB", "GB"]:
            if self.size < 1024:
                return f"{self.size:.1f}{unit}"
            self.size /= 1024
        return f"{self.size:.1f}TB"


# ============================================================
# DIRECTORY MANAGEMENT (SRP - só diretórios)
# ============================================================

def ensure_dir(path: Union[str, Path]) -> Path:
    """
    Cria diretório (inclui parents) se não existe.

    Args:
        path: Caminho do diretório.

    Returns:
        Path resolvido.
    """
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_parent_dir(path: Union[str, Path]) -> Path:
    """Cria diretório pai do arquivo."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def list_files(
    directory: Union[str, Path],
    pattern: str = "*",
    recursive: bool = False,
    include_dirs: bool = False,
) -> List[FileInfo]:
    """
    Lista arquivos com metadados.

    Args:
        directory: Diretório base.
        pattern: Glob pattern (ex: "*.yaml", "profile_*.yaml").
        recursive: Busca recursiva.
        include_dirs: Incluir diretórios no resultado.

    Returns:
        Lista de FileInfo ordenada por modified desc.
    """
    directory = Path(directory)
    if not directory.exists():
        return []

    glob_method = directory.rglob if recursive else directory.glob
    files = []

    for p in glob_method(pattern):
        if not include_dirs and p.is_dir():
            continue
        stat = p.stat()
        files.append(FileInfo(
            path=p,
            name=p.name,
            size=stat.st_size,
            modified=datetime.fromtimestamp(stat.st_mtime),
            extension=p.suffix.lower(),
        ))

    return sorted(files, key=lambda f: f.modified, reverse=True)


def get_dir_size(path: Union[str, Path]) -> int:
    """Retorna tamanho total do diretório em bytes."""
    path = Path(path)
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


# ============================================================
# ATOMIC WRITE (SRP - escrita segura)
# ============================================================

def atomic_write(
    path: Union[str, Path],
    content: str,
    encoding: str = "utf-8",
    mode: int = 0o644,
) -> Path:
    """
    Escrita atômica: escreve em temp + rename.

    Garante que o arquivo ou existe completo, ou não existe.
    Evita corrupção se processo morrer no meio da escrita.

    Args:
        path: Arquivo destino.
        content: Conteúdo string.
        encoding: Encoding (default utf-8).
        mode: Permissões do arquivo.

    Returns:
        Path do arquivo escrito.
    """
    path = Path(path)
    ensure_parent_dir(path)

    temp_path = path.with_suffix(path.suffix + ".tmp")

    try:
        with open(temp_path, "w", encoding=encoding) as f:
            f.write(content)
        temp_path.chmod(mode)
        temp_path.replace(path)  # Atomic on POSIX
        return path
    except Exception:
        # Cleanup temp se falhou
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise


def atomic_write_bytes(
    path: Union[str, Path],
    content: bytes,
    mode: int = 0o644,
) -> None:
    """Versão bytes do atomic_write."""
    path = Path(path)
    ensure_parent_dir(path)

    temp_path = path.with_suffix(path.suffix + ".tmp")

    try:
        with open(temp_path, "wb") as f:
            f.write(content)
        temp_path.chmod(mode)
        temp_path.replace(path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise


# ============================================================
# BACKUP (SRP - versionamento de arquivos)
# ============================================================

def backup_file(
    path: Union[str, Path],
    backup_dir: Optional[Union[str, Path]] = None,
    max_backups: int = 10,
) -> Optional[Path]:
    """
    Cria backup timestampado do arquivo.

    Args:
        path: Arquivo para backup.
        backup_dir: Diretório de backups (default: mesmo dir/backups/).
        max_backups: Máximo de backups a manter.

    Returns:
        Path do backup criado ou None se arquivo não existe.
    """
    path = Path(path)
    if not path.exists():
        return None

    if backup_dir is None:
        backup_dir = path.parent / "backups" / path.stem
    else:
        backup_dir = Path(backup_dir)

    ensure_dir(backup_dir)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_name = f"{path.stem}_{timestamp}{path.suffix}"
    backup_path = backup_dir / backup_name

    shutil.copy2(path, backup_path)

    # Prune old backups
    _prune_backups(backup_dir, path.stem, path.suffix, max_backups)

    return backup_path


def _prune_backups(backup_dir: Path, stem: str, suffix: str, max_backups: int) -> None:
    """Remove backups antigos mantendo os N mais recentes."""
    pattern = f"{stem}_*{suffix}"
    backups = sorted(backup_dir.glob(pattern), key=lambda p: p.stat().st_mtime)
    for old in backups[:-max_backups]:
        old.unlink(missing_ok=True)


def list_backups(path: Union[str, Path], backup_dir: Optional[Union[str, Path]] = None) -> List[Path]:
    """Lista backups disponíveis (mais recente primeiro)."""
    path = Path(path)
    if backup_dir is None:
        backup_dir = path.parent / "backups" / path.stem
    else:
        backup_dir = Path(backup_dir)

    if not backup_dir.exists():
        return []

    pattern = f"{path.stem}_*{path.suffix}"
    return sorted(backup_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)


def restore_backup(
    path: Union[str, Path],
    backup_path: Union[str, Path],
    create_backup_before: bool = True,
) -> bool:
    """
    Restaura arquivo a partir de backup.

    Args:
        path: Arquivo destino.
        backup_path: Backup a restaurar.
        create_backup_before: Fazer backup do arquivo atual antes.

    Returns:
        True se restaurou com sucesso.
    """
    path = Path(path)
    backup_path = Path(backup_path)

    if not backup_path.exists():
        return False

    if create_backup_before and path.exists():
        backup_file(path)

    ensure_parent_dir(path)
    shutil.copy2(backup_path, path)
    return True


# ============================================================
# YAML HELPERS (SRP - só YAML)
# ============================================================

def load_yaml(path: Union[str, Path], default: Any = None) -> Any:
    """
    Carrega arquivo YAML.

    Args:
        path: Caminho do arquivo.
        default: Valor padrão se arquivo não existe ou vazio.

    Returns:
        Dados parseados ou default.
    """
    path = Path(path)
    if not path.exists():
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if data is not None else default
    except yaml.YAMLError as e:
        raise ValueError(f"YAML inválido em {path}: {e}")


def save_yaml(
    path: Union[str, Path],
    data: Any,
    atomic: bool = True,
    backup: bool = True,
    default_flow_style: bool = False,
    sort_keys: bool = False,
    allow_unicode: bool = True,
) -> Path:
    """
    Salva dados em YAML.

    Args:
        path: Arquivo destino.
        data: Dados para serializar.
        atomic: Usar escrita atômica.
        backup: Criar backup antes de sobrescrever.
        default_flow_style: Estilo YAML (False = block).
        sort_keys: Ordenar chaves.
        allow_unicode: Permitir unicode (não escapa).

    Returns:
        Path do arquivo salvo.
    """
    path = Path(path)

    if backup and path.exists():
        backup_file(path)

    content = yaml.dump(
        data,
        default_flow_style=default_flow_style,
        sort_keys=sort_keys,
        allow_unicode=allow_unicode,
    )

    if atomic:
        atomic_write(path, content)
    else:
        ensure_parent_dir(path)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    return path


# ============================================================
# JSON HELPERS (SRP - só JSON)
# ============================================================

class JSONEncoder(json.JSONEncoder):
    """Encoder customizado para tipos comuns."""

    def default(self, obj):
        if hasattr(obj, "isoformat"):  # datetime, date
            return obj.isoformat()
        if hasattr(obj, "__dict__"):  # dataclass, objeto
            return obj.__dict__
        if hasattr(obj, "value"):  # Enum
            return obj.value
        return super().default(obj)


def load_json(path: Union[str, Path], default: Any = None) -> Any:
    """
    Carrega arquivo JSON.

    Args:
        path: Caminho do arquivo.
        default: Valor padrão se arquivo não existe ou vazio.

    Returns:
        Dados parseados ou default.
    """
    path = Path(path)
    if not path.exists():
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON inválido em {path}: {e}")


def save_json(
    path: Union[str, Path],
    data: Any,
    atomic: bool = True,
    backup: bool = True,
    indent: int = 2,
    ensure_ascii: bool = False,
) -> Path:
    """
    Salva dados em JSON.

    Args:
        path: Arquivo destino.
        data: Dados para serializar.
        atomic: Usar escrita atômica.
        backup: Criar backup antes de sobrescrever.
        indent: Indentação.
        ensure_ascii: False = mantém unicode.

    Returns:
        Path do arquivo salvo.
    """
    path = Path(path)

    if backup and path.exists():
        backup_file(path)

    content = json.dumps(data, cls=JSONEncoder, indent=indent, ensure_ascii=ensure_ascii)

    if atomic:
        atomic_write(path, content)
    else:
        ensure_parent_dir(path)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    return path


# ============================================================
# GENERIC SERIALIZATION (OCP - extensível para novos formatos)
# ============================================================

class Serializer:
    """Interface para serializadores (Strategy Pattern)."""

    def load(self, path: Union[str, Path], default: Any = None) -> Any:
        raise NotImplementedError

    def save(self, path: Union[str, Path], data: Any, **kwargs) -> Path:
        raise NotImplementedError

    @property
    def extension(self) -> str:
        raise NotImplementedError


class YAMLSerializer(Serializer):
    @property
    def extension(self) -> str:
        return ".yaml"

    def load(self, path: Union[str, Path], default: Any = None) -> Any:
        return load_yaml(path, default)

    def save(self, path: Union[str, Path], data: Any, **kwargs) -> Path:
        return save_yaml(path, data, **kwargs)


class JSONSerializer(Serializer):
    @property
    def extension(self) -> str:
        return ".json"

    def load(self, path: Union[str, Path], default: Any = None) -> Any:
        return load_json(path, default)

    def save(self, path: Union[str, Path], data: Any, **kwargs) -> Path:
        return save_json(path, data, **kwargs)


# Registry de serializadores (OCP - fácil adicionar TOML, pickle, etc.)
_SERIALIZERS: Dict[str, Serializer] = {
    ".yaml": YAMLSerializer(),
    ".yml": YAMLSerializer(),
    ".json": JSONSerializer(),
}


def register_serializer(ext: str, serializer: Serializer) -> None:
    """Registra novo serializador (ex: TOML, pickle)."""
    _SERIALIZERS[ext.lower()] = serializer


def get_serializer(path: Union[str, Path]) -> Serializer:
    """Retorna serializador baseado na extensão."""
    path = Path(path)
    ext = path.suffix.lower()
    return _SERIALIZERS.get(ext, YAMLSerializer())  # Default YAML


def load_file(path: Union[str, Path], default: Any = None) -> Any:
    """Carrega arquivo auto-detectando formato pela extensão."""
    return get_serializer(path).load(path, default)


def save_file(path: Union[str, Path], data: Any, **kwargs) -> Path:
    """Salva arquivo auto-detectando formato pela extensão."""
    return get_serializer(path).save(path, data, **kwargs)


# ============================================================
# PROFILE-SPECIFIC (Convenience para profile.yaml)
# ============================================================

def load_profile_yaml(path: Optional[Union[str, Path]] = None) -> Dict:
    """Carrega profile.yaml (usa settings se path não dado)."""
    if path is None:
        settings = get_settings()
        path = settings.profile_path
    return load_yaml(path, default={})


def save_profile_yaml(data: Dict, path: Optional[Union[str, Path]] = None) -> Path:
    """Salva profile.yaml com backup."""
    if path is None:
        settings = get_settings()
        path = settings.profile_path
    return save_yaml(path, data, atomic=True, backup=True)


# ============================================================
# CV OUTPUT (Convenience para CVs gerados)
# ============================================================

def get_cv_output_dir(settings=None) -> Path:
    """Retorna diretório de output de CVs."""
    settings = settings or get_settings()
    ensure_dir(settings.cvs_dir)
    return settings.cvs_dir


def save_cv_markdown(content: str, filename: str, settings=None) -> Path:
    """Salva CV em Markdown."""
    output_dir = get_cv_output_dir(settings)
    path = output_dir / filename
    if not path.suffix:
        path = path.with_suffix(".md")
    return atomic_write(path, content)


def save_cv_json(data: Dict, filename: str, settings=None) -> Path:
    """Salva CV em JSON (dados estruturados)."""
    output_dir = get_cv_output_dir(settings)
    path = output_dir / filename
    if not path.suffix:
        path = path.with_suffix(".json")
    return save_json(path, data, atomic=True, backup=False)


def list_cvs(settings=None) -> List[FileInfo]:
    """Lista CVs gerados."""
    output_dir = get_cv_output_dir(settings)
    return list_files(output_dir, pattern="*.md") + list_files(output_dir, pattern="*.pdf")


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    # Types
    "FileInfo",
    # Directory
    "ensure_dir",
    "ensure_parent_dir",
    "list_files",
    "get_dir_size",
    # Atomic write
    "atomic_write",
    "atomic_write_bytes",
    # Backup
    "backup_file",
    "list_backups",
    "restore_backup",
    # YAML
    "load_yaml",
    "save_yaml",
    # JSON
    "load_json",
    "save_json",
    "JSONEncoder",
    # Generic serialization
    "Serializer",
    "YAMLSerializer",
    "JSONSerializer",
    "register_serializer",
    "get_serializer",
    "load_file",
    "save_file",
    # Profile specific
    "load_profile_yaml",
    "save_profile_yaml",
    # CV specific
    "get_cv_output_dir",
    "save_cv_markdown",
    "save_cv_json",
    "list_cvs",
]