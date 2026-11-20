"""Safe, stable resource boundary errors; original causes remain inspectable."""

from bca.core.errors import BCAError


class AssetError(BCAError):
    code = "asset.error"


class AssetManifestError(AssetError):
    code = "asset.manifest"


class AssetProfileError(AssetError):
    code = "asset.profile"


class AssetNotFoundError(AssetError):
    code = "asset.not_found"


class AssetSelectionError(AssetError):
    code = "asset.selection"


class AssetPathError(AssetError):
    code = "asset.path"


class AssetDecodeError(AssetError):
    code = "asset.decode"


class AssetValidationError(AssetError):
    code = "asset.validation"


class AssetClosedError(AssetError):
    code = "asset.closed"
