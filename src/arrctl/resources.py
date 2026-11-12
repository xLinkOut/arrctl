"""Registry of API resources that can be managed as collections."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResourceDef:
    name: str
    path: str
    identity: tuple[str, ...]
    create: bool = True
    update: bool = True
    delete: bool = True
    has_schema: bool = False
    prepare: str | None = None


# Fields returned by GET that must not be sent back on create and are not
# interesting in a source-of-truth file.
READ_ONLY_FIELDS = {
    "id",
    "implementationName",
    "infoLink",
    "presets",
    "message",
    "testCommand",
    "status",
    "capabilities",
    "added",
    "sortName",
    "definitionName",
    "description",
    "encoding",
    "indexerUrls",
    "legacyUrls",
    "privacy",
    "supportsRss",
    "supportsSearch",
    "supportsPagination",
    "supportsRedirect",
    "link",
    "redirect",
    "totalSpace",
    "freeSpace",
    "accessible",
    "unmappedFolders",
}

# Fields that are output-only or instance-specific. They are removed by `pull`.
PULL_EXCLUDE = READ_ONLY_FIELDS

# Fields that need a restart (or may move the API endpoint).
RESTART_FIELDS = {
    "bindAddress",
    "port",
    "sslPort",
    "enableSsl",
    "urlBase",
    "sslCertPath",
    "sslCertPassword",
}

COMMON_RESOURCES: dict[str, ResourceDef] = {
    "downloadclient": ResourceDef("downloadclient", "downloadclient", ("name",), has_schema=True),
    "indexer": ResourceDef("indexer", "indexer", ("name",), has_schema=True),
    "notification": ResourceDef("notification", "notification", ("name",), has_schema=True),
    "tag": ResourceDef("tag", "tag", ("label",)),
    "customfilter": ResourceDef("customfilter", "customfilter", ("label",)),
    "remotepathmapping": ResourceDef(
        "remotepathmapping", "remotepathmapping", ("host", "remotePath")
    ),
    "rootfolder": ResourceDef("rootfolder", "rootfolder", ("path",), update=False, delete=False),
    "qualityprofile": ResourceDef("qualityprofile", "qualityprofile", ("name",), has_schema=True),
    "qualitydefinition": ResourceDef(
        "qualitydefinition",
        "qualitydefinition",
        ("quality.name",),
        create=False,
        delete=False,
        prepare="quality_definition",
    ),
    "customformat": ResourceDef("customformat", "customformat", ("name",), has_schema=True),
    "delayprofile": ResourceDef("delayprofile", "delayprofile", ("order",)),
    "releaseprofile": ResourceDef("releaseprofile", "releaseprofile", ("name",)),
    "metadata": ResourceDef("metadata", "metadata", ("name",), has_schema=True),
    "autotagging": ResourceDef("autotagging", "autotagging", ("name",), has_schema=True),
}

SONARR = dict(COMMON_RESOURCES)
SONARR.update(
    {
        "importlist": ResourceDef("importlist", "importlist", ("name",), has_schema=True),
        "importlistexclusion": ResourceDef(
            "importlistexclusion", "importlistexclusion", ("foreignId", "title")
        ),
        "languageprofile": ResourceDef(
            "languageprofile", "languageprofile", ("name",), has_schema=True
        ),
    }
)

RADARR = dict(COMMON_RESOURCES)
RADARR.update(
    {
        "importlist": ResourceDef("importlist", "importlist", ("name",), has_schema=True),
        "exclusions": ResourceDef("exclusions", "exclusions", ("foreignId", "movieTitle")),
    }
)

LIDARR = dict(COMMON_RESOURCES)
LIDARR.update(
    {
        "importlist": ResourceDef("importlist", "importlist", ("name",), has_schema=True),
        "importlistexclusion": ResourceDef(
            "importlistexclusion", "importlistexclusion", ("foreignId", "artistName")
        ),
        "metadataprofile": ResourceDef(
            "metadataprofile", "metadataprofile", ("name",), has_schema=True
        ),
    }
)

WHISPARR = dict(COMMON_RESOURCES)
WHISPARR.update(
    {
        "importlist": ResourceDef("importlist", "importlist", ("name",), has_schema=True),
        "exclusions": ResourceDef("exclusions", "exclusions", ("foreignId", "movieTitle")),
    }
)

PROWLARR: dict[str, ResourceDef] = {
    "downloadclient": ResourceDef("downloadclient", "downloadclient", ("name",), has_schema=True),
    "indexer": ResourceDef("indexer", "indexer", ("name",), has_schema=True),
    "notification": ResourceDef("notification", "notification", ("name",), has_schema=True),
    "tag": ResourceDef("tag", "tag", ("label",)),
    "customfilter": ResourceDef("customfilter", "customfilter", ("label",)),
    "application": ResourceDef("application", "applications", ("name",), has_schema=True),
    "appprofile": ResourceDef("appprofile", "appprofile", ("name",), has_schema=True),
    "indexerproxy": ResourceDef("indexerproxy", "indexerproxy", ("name",), has_schema=True),
}

RESOURCES: dict[str, dict[str, ResourceDef]] = {
    "sonarr": SONARR,
    "radarr": RADARR,
    "lidarr": LIDARR,
    "whisparr": WHISPARR,
    "prowlarr": PROWLARR,
    "bazarr": {},
}

# Config singletons, in the order they should be applied. Host is last
# because changing bind/port/urlBase can move the endpoint.
CONFIG_ORDER = [
    "ui",
    "mediamanagement",
    "naming",
    "indexer",
    "downloadclient",
    "importlist",
    "metadata",
    "metadataprovider",
    "development",
    "host",
]

# Apply independent resources first so later resources can reference them by
# name (tags, profiles, download clients, ...).
RESOURCE_PRIORITY = [
    "tag",
    "rootfolder",
    "qualityprofile",
    "metadataprofile",
    "languageprofile",
    "downloadclient",
    "indexerproxy",
    "appprofile",
    "indexer",
    "notification",
    "customformat",
    "delayprofile",
    "releaseprofile",
    "metadata",
    "autotagging",
    "remotepathmapping",
    "customfilter",
    "importlist",
    "importlistexclusion",
    "exclusions",
    "application",
    "qualitydefinition",
]

APP_LABELS = {
    "sonarr": "Sonarr",
    "radarr": "Radarr",
    "lidarr": "Lidarr",
    "whisparr": "Whisparr",
    "prowlarr": "Prowlarr",
    "bazarr": "Bazarr",
}


def get_resource(app: str, name: str) -> ResourceDef | None:
    return RESOURCES.get(app, {}).get(name)
