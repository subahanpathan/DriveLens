from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ItemKind(StrEnum):
    FILE = "File"
    FOLDER = "Folder"


class Category(StrEnum):
    WINDOWS_SYSTEM = "🪟 Windows/System files"
    INSTALLED_APPLICATION = "📦 Installed applications"
    DRIVER = "Driver"
    USER_FILE = "👤 My personal/user files"
    DOWNLOADED = "🌐 Downloaded/external files"
    TEMPORARY = "🧹 Temporary/cache files"
    APPLICATION_DATA = "Application Data"
    DEVELOPMENT = "🛠️ Development/tools"
    UNKNOWN = "❓ Unknown"
    SUSPICIOUS = "Potentially Suspicious"


class DeletionRisk(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class Classification:
    category: str
    purpose: str
    windows_required: str
    associated_application: str
    deletion_risk: str
    can_delete: str
    confidence: int
    reason: str
    is_protected: bool = False


@dataclass(frozen=True)
class ScanCounts:
    files: int = 0
    folders: int = 0
    total_size: int = 0
    inaccessible: int = 0